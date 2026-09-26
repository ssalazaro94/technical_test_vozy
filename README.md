# Auditoría automática de llamadas de cobranza

Servicio que evalúa conversaciones del agente de voz **Lina** (Banco Andino, entidad ficticia) contra una rúbrica de 21 criterios derivada de sus 10 reglas de negocio. Para cada conversación devuelve el resultado de cada criterio (`cumple`, `no_cumple`, `no_aplica`) con la cita textual que lo justifica, un puntaje de 0 a 100 y una severidad global. Para un conjunto de conversaciones devuelve además un reporte agregado con la tasa de cumplimiento por criterio y las fallas más frecuentes.

## Documentación

| Documento | Contenido |
|---|---|
| [docs/rubrica.md](docs/rubrica.md) | Criterios, por qué se definieron así, severidad, puntaje y casos límite |
| [docs/decisiones-tecnicas.md](docs/decisiones-tecnicas.md) | Qué se resuelve con código y qué con LLM, manejo de errores y limitaciones conocidas |
| [docs/costos.md](docs/costos.md) | Costo estimado de evaluar 1.000 conversaciones |
| [docs/api.md](docs/api.md) | Endpoints, ejemplos de uso y formato de errores |
| [docs/hallazgos.md](docs/hallazgos.md) | Informe para el cliente: fallas principales del agente y ajustes recomendados |

## Arquitectura

El servicio sigue una arquitectura hexagonal (puertos y adaptadores). El dominio contiene la rúbrica y no depende de ningún framework, base de datos ni proveedor de LLM; todo lo externo entra por puertos y se conecta en un único punto (`bootstrap.py`).

```mermaid
flowchart LR
    subgraph Adaptadores de entrada
        HTTP[FastAPI<br/>/v1/audits]
    end
    subgraph Aplicación
        SVC[AuditService<br/>concurrencia y degradación]
        EXT[FactExtractor<br/>prompt y autocorrección]
    end
    subgraph Dominio
        ENG[Motor de rúbrica<br/>21 criterios]
        TXT[Utilidades deterministas<br/>montos, dígitos, fechas]
        REP[Puntaje y reporte]
    end
    subgraph Adaptadores de salida
        GEM[Gemini]
        OFF[Sin LLM / replay]
        PG[(Postgres<br/>Supabase)]
    end
    HTTP --> SVC --> EXT
    EXT -- puerto StructuredLanguageModel --> GEM
    EXT -.-> OFF
    SVC -- puerto AuditRepository --> PG
    SVC --> ENG --> TXT
    ENG --> REP
```

### Flujo de una auditoría

1. **Extracción de hechos (LLM).** Una sola llamada por conversación. El modelo no decide si una regla se cumple: señala en qué turno ocurrió cada hecho relevante (por ejemplo, "el agente informó la deuda en el turno 4", "el cliente pidió un asesor en el turno 5"). La respuesta se valida con un esquema estricto y contra la transcripción: un turno fuera de rango o del hablante equivocado provoca un reintento con el error como retroalimentación.
2. **Veredictos (código).** Cada criterio es una función pura que combina esos hechos con los datos del cliente: compara dígitos del documento, convierte montos dichos en palabras, calcula la ventana de fechas, busca términos prohibidos.
3. **Citas (código).** La evidencia se copia de la transcripción por índice de turno, por lo que siempre es literal. Un `no_cumple` sin cita es rechazado por el propio modelo de salida.
4. **Puntaje y reporte.** Puntaje ponderado por severidad, severidad global y agregación por criterio.
5. **Persistencia.** La auditoría (o la ejecución completa, en una sola transacción) se guarda en Postgres y se puede recuperar por su identificador. Si la base falla, la auditoría se entrega igual con `persisted: false`.

Si el LLM no está disponible (sin clave, cuota agotada, error de red), la auditoría no falla: se evalúan los criterios que solo dependen de código, el resto queda `indeterminado` y la auditoría se marca `parcial` con la causa.

### Estructura del código

```
src/callaudit/
  domain/           rúbrica, modelos de entrada y salida, puntaje, reporte (sin dependencias externas)
    criteria/       un módulo por grupo de reglas (R1-R2, R3-R4, R5-R6, R7-R8, R9-R10)
    text/           normalización, números y fechas en español, léxicos
  application/      casos de uso, prompts, puertos, especificación por defecto del agente
  adapters/
    http/           FastAPI: rutas, esquemas, ejemplos de Swagger, errores
    llm/            Gemini, modelo deshabilitado, limitador de ritmo
    facts/          replay de hechos anotados (solo desarrollo)
    persistence/    Postgres (SQLAlchemy async) y repositorio nulo
  bootstrap.py      composición: qué adaptador implementa cada puerto
  config.py         configuración por variables de entorno
supabase/migrations/     esquema SQL (el mismo en local y en Supabase)
Dockerfile, compose.yaml imagen de producción y stack local
tests/
  integration/      repositorio contra un Postgres real
  golden/           la rúbrica reproduce la evaluación manual de las 20 conversaciones
  unit/             utilidades, motor, extracción, servicio, adaptadores, API
scripts/
  evaluate_extraction.py   precisión del LLM real frente a la anotación manual
```

## Cómo correrlo localmente

Hay dos formas: el stack completo con Docker (recomendado para probar todo, sin clave de LLM) o el servicio directo con uv (para desarrollar).

### Opción A: stack completo con Docker, sin LLM real

Levanta la misma imagen que se despliega en producción y un Postgres local con las mismas migraciones. En lugar de llamar a Gemini, el proveedor `replay` sirve los hechos anotados a mano (`tests/fixtures/golden_facts.json`), así que las auditorías de las 20 conversaciones salen completas.

Requisitos: Docker con Compose.

```bash
git clone git@github.com:ssalazaro94/technical_test_vozy.git
cd technical_test_vozy
docker compose up --build
```

- Swagger: http://localhost:8080/docs
- Estado: http://localhost:8080/health (debe indicar `replay:golden_facts.json` y `database: ok`)

Los puertos se eligen con `API_PORT` (por defecto 8080) y `DB_PORT` (por defecto 5433), en la terminal o en `.env`:

```bash
API_PORT=8089 DB_PORT=6543 docker compose up --build   # API en http://localhost:8089/docs
```

`API_PORT` es también el puerto en el que escucha la API dentro del contenedor, igual que la variable `PORT` que inyecta la plataforma en producción. En los ejemplos siguientes, reemplazar 8080 y 5433 si se cambiaron.

```bash
# Auditar el archivo de conversaciones
curl -F "file=@/ruta/al/dataset.json;type=application/json" \
  http://localhost:8080/v1/audits/dataset/file > results.json

# Recuperar la ejecución guardada
curl http://localhost:8080/v1/reports/<run_id>

# Consultar la base
docker compose exec db psql -U postgres -c "select conversation_id, severity, score, failed_criteria from callaudit.conversation_audits"
```

`docker compose down -v` detiene todo y borra la base local. Las migraciones se aplican solas al crear la base por primera vez.

### Opción B: servicio directo con uv

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) y, opcionalmente, una API key de Google Gemini ([Google AI Studio](https://aistudio.google.com/), tier gratuito).

```bash
uv sync
cp .env.example .env      # definir GEMINI_API_KEY; sin clave funciona en modo degradado
uv run uvicorn callaudit.main:app --reload
```

- Swagger: http://localhost:8000/docs
- Sin `DATABASE_URL` las auditorías se devuelven pero no se guardan; con la base del stack de Docker: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/postgres`.

### Tests y calidad

```bash
uv run pytest                          # tests sin red: LLM y SDK simulados
uv run ruff check src tests scripts    # lint
uv run ruff format --check src tests scripts
uv run mypy src tests scripts          # tipado estricto
```

Los tests del repositorio de Postgres se ejecutan solo con una base migrada disponible:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/postgres uv run pytest tests/integration
```

Los tests que usan las 20 conversaciones del cliente necesitan la ruta del archivo en `LOCAL_DATASET_PATH` (variable de entorno o `.env`); sin ella se omiten y el resto de la suite se ejecuta normalmente.

### Medir la precisión del LLM

Con `GEMINI_API_KEY` y `LOCAL_DATASET_PATH` definidos:

```bash
uv run python scripts/evaluate_extraction.py --out evaluation/extraction.json
```

Compara los hechos extraídos por el modelo con la anotación manual y reporta exactitud por campo, y precisión y recall de los veredictos.

### Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `none` (solo criterios de código) o `replay` (solo desarrollo) |
| `LLM_MODEL` | `gemini-2.5-flash` | Modelo de Gemini |
| `GEMINI_API_KEY` | vacío | Clave de Google AI Studio |
| `LLM_MAX_CONCURRENCY` | `4` | Llamadas simultáneas al LLM |
| `LLM_REQUESTS_PER_MINUTE` | `10` | Ritmo máximo de llamadas (límite del tier gratuito) |
| `LLM_MAX_ATTEMPTS` | `4` | Intentos ante errores transitorios (429, 5xx, red) |
| `LLM_TIMEOUT_SECONDS` | `90` | Tiempo máximo por llamada |
| `EXTRACTION_MAX_ATTEMPTS` | `2` | Intentos ante respuestas inválidas o inconsistentes |
| `REPLAY_FACTS_PATH` | vacío | Con `replay`: archivo de hechos anotados a reproducir |
| `DATABASE_URL` | vacío | Postgres (`postgresql+asyncpg://...`); sin ella no se guardan auditorías |
| `DATABASE_TIMEOUT_SECONDS` | `10` | Tiempo máximo de conexión y de consulta |
| `LOCAL_DATASET_PATH` | vacío | Solo tests y scripts locales: ruta al archivo de conversaciones |
