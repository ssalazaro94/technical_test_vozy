# Decisiones técnicas y limitaciones conocidas

## Stack

| Componente | Elección | Motivo |
|---|---|---|
| Lenguaje | Python 3.12 | SDK oficial de Gemini, ecosistema de validación maduro, sintaxis de genéricos (PEP 695) para el puerto del LLM |
| Framework HTTP | FastAPI | Validación de entrada y salida con los mismos modelos Pydantic, OpenAPI y Swagger generados automáticamente, soporte async nativo |
| Validación | Pydantic v2 | La salida se valida por construcción: un `no_cumple` sin cita o un campo de más no se pueden serializar |
| LLM | Gemini 3.8 Flash (tier gratuito) | Costo cero, salida JSON restringida por esquema, modelo Flash estable vigente (Google retiró Gemini 2.5 Flash para cuentas nuevas) |
| Entorno | uv + `pyproject.toml` + `uv.lock` | Instalación reproducible y rápida |
| Calidad | pytest, ruff, mypy en modo estricto | Tests sin red, lint y tipado estático en todo el código |
| Persistencia | Postgres en Supabase, con SQLAlchemy async y asyncpg | SQL estándar sin acoplarse al SDK de Supabase: cambiar de proveedor es cambiar `DATABASE_URL` |
| Despliegue | Docker (multi-stage, usuario sin privilegios) | La imagen que se prueba en local es la que corre en producción |

## Arquitectura hexagonal

El dominio (rúbrica, puntaje, reporte) no importa FastAPI, el SDK de Gemini ni ningún driver. Lo necesita todo a través de puertos (`typing.Protocol`), y un único módulo (`bootstrap.py`) decide qué adaptador implementa cada uno.

Por qué este patrón:

- **Proveedor de LLM intercambiable.** Cambiar Gemini por otro proveedor es escribir un adaptador del puerto `StructuredLanguageModel` y cambiar `LLM_PROVIDER`; la rúbrica no se toca.
- **Tests sin red.** Los tests inyectan un LLM simulado: son deterministas, rápidos y no consumen cuota.
- **Degradación.** Sin LLM se inyecta un adaptador deshabilitado y el servicio sigue funcionando.

## Qué se resuelve con código y qué con LLM

La división es el centro del diseño: **el LLM localiza hechos y el código emite los veredictos.**

El modelo recibe la transcripción con los turnos numerados y devuelve una ficha estructurada (`ConversationFacts`): quién atendió, en qué turno se informó la deuda, en qué turno se acordó el pago, si el cliente pidió un asesor, qué turnos presionan al cliente, etc. Nunca devuelve "cumple" o "no cumple"; el esquema lo impide (`additionalProperties: false`).

| Se resuelve con código | Por qué |
|---|---|
| Presentación, aviso de grabación y nombre completo (R1, R2.a) | Frases fijas verificables con patrones sobre el texto normalizado (sin tildes, sin mayúsculas) |
| Coincidencia de los dígitos del documento (R2.c) | Comparación exacta; incluye dígitos dictados en palabras |
| Orden de los turnos: dígitos pedidos antes de revelar (R2.b) | Aritmética sobre índices |
| Monto informado frente al registrado (R4.a) | Un LLM no convierte con fiabilidad "dos millones seiscientos veinte mil" y lo compara con 2.260.000; un parser de números en español sí |
| Fecha de vencimiento y fecha de pago (R4.b, R5) | Resolver "el sábado 26" respecto a la fecha de la llamada y verificar la ventana de 5 días es aritmética de calendario, donde los LLM fallan con frecuencia |
| Términos legales prohibidos (R10.a) | Léxico fijo: la regla prohíbe mencionarlos, de modo que la sola presencia es suficiente |
| Citas | Se copian de la transcripción por índice de turno: son literales por construcción |
| Puntaje, severidad y reporte | Fórmulas deterministas y reproducibles |

| Se resuelve con LLM | Por qué |
|---|---|
| Quién atendió (titular o tercero) | Requiere comprender respuestas como "No, habla la esposa" |
| En qué turno se revela la deuda | El código verifica después el contenido de ese turno |
| Intención del cliente: pedir un asesor, disputar, reportar un pago, pedir un beneficio | Lenguaje natural con muchas formulaciones posibles |
| Si el agente ofreció un beneficio o solo lo mencionó para negarlo | Depende del sentido de la frase |
| Resumen de cierre y despedida | Formulaciones variables |
| Presión o falta de empatía | Juicio sobre el tono en contexto |
| Paráfrasis de amenazas legales que el léxico no captura | Complementa al código (se toma la unión de ambos) |

Beneficios de esta división:

- **Menos falsos positivos.** Lo que se puede calcular no se deja al criterio del modelo.
- **Reproducibilidad.** Con la misma ficha de hechos, el veredicto es siempre el mismo.
- **Validación de la respuesta del modelo.** Cada turno señalado debe existir y pertenecer al hablante esperado (un turno del agente no puede ser "el cliente pidió un asesor"). Si no cuadra, se repregunta al modelo indicándole el error concreto.
- **Costo.** Una sola llamada por conversación.

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Error transitorio del LLM (429 por minuto, 5xx, timeout, red) | Reintento con backoff exponencial y jitter (hasta 4 intentos, espera máxima 30 s). Si Google indica cuánto esperar (`RetryInfo`, por ejemplo "44s"), se respeta esa espera, con un tope de 60 s |
| Cuota diaria del LLM agotada (429 con `QuotaFailure` diaria) | Sin reintento: se responde de inmediato y el adaptador no vuelve a llamar al modelo hasta la medianoche del Pacífico, cuando se renueva la cuota. Google cuenta también las peticiones rechazadas, así que reintentar solo alarga la respuesta |
| Error permanente del LLM (400, 401, 403, 404) | Sin reintento: repetir no lo resuelve y solo consume cuota |
| Respuesta del LLM que no cumple el esquema o con turnos inconsistentes | Nueva solicitud con los problemas detectados como retroalimentación (hasta 2 intentos) |
| El LLM no se recupera o no está configurado | La auditoría se entrega igual: criterios de código evaluados, el resto `indeterminado`, `analysis: "parcial"` y una advertencia con la causa. Respuesta HTTP 200 |
| Una conversación falla dentro de un lote | Solo esa conversación se degrada; el resto del lote continúa |
| Entrada inválida | HTTP 422 con la ubicación exacta de cada error |
| Archivo o lote demasiado grande | HTTP 413 (máximo 2 MB y 100 conversaciones por ejecución) |
| Error inesperado | HTTP 500 con un mensaje genérico; el detalle solo va al log del servidor |
| Presupuesto diario del servicio agotado (`LLM_DAILY_CALL_BUDGET`) | No se llama al modelo; las conversaciones nuevas salen parciales con el aviso y las ya analizadas salen del caché. Si el contador no responde, tampoco se llama al modelo (falla cerrado) |
| Demasiadas solicitudes de un cliente (`CLIENT_REQUESTS_PER_HOUR`) | HTTP 429 con `Retry-After` en las rutas de auditoría |

Además, un limitador de ritmo del lado del cliente separa las llamadas (4 por minuto por defecto, bajo el límite de 5 del tier gratuito de `gemini-3.8-flash`) y un semáforo limita las llamadas simultáneas (2 por defecto).

## Persistencia

- **Qué se guarda.** Cada auditoría completa como JSONB (es la fuente de verdad al leerla) más columnas consultables: conversación, puntaje, severidad, resultado y criterios fallidos (con índice GIN para buscar por criterio). Cada ejecución guarda además su reporte agregado. Una ejecución y sus auditorías se escriben en una sola transacción.
- **Esquema propio (`callaudit`) y RLS activado.** Supabase expone el esquema `public` a través de su API REST con la clave pública del proyecto. Las tablas viven en otro esquema y además tienen row level security, de modo que no son accesibles desde esa API. El servicio se conecta como dueño de la base.
- **Conexión por el pooler en modo sesión.** El plan gratuito de la plataforma de despliegue solo sale por IPv4 y la conexión directa de Supabase es IPv6, así que se usa el pooler, que acepta IPv4. El modo sesión conserva la conexión física, compatible con las sentencias preparadas de asyncpg, y es adecuado para un proceso de larga vida con un pool pequeño.
- **Tolerante a fallos.** La persistencia nunca bloquea la respuesta: si la base falla, la auditoría se entrega con `persisted: false` y un aviso. Sin `DATABASE_URL` el servicio funciona sin guardar nada. Las conexiones se verifican antes de usarse (`pool_pre_ping`), así que el servicio se recupera solo cuando la base vuelve.
- **Migraciones versionadas** en `supabase/migrations/`: el mismo SQL crea el esquema en el Postgres local y en Supabase.

## Caché de hechos

- **Qué se guarda:** solo extracciones del modelo que ya pasaron la validación contra la transcripción. Los fallos nunca se guardan.
- **Clave:** huella SHA-256 de todo lo que determina la respuesta del modelo: las instrucciones (con la especificación del agente), la conversación tal como se envía al modelo (datos del cliente, fecha y cada turno), el esquema de respuesta y el nombre del modelo. El `id` de la conversación no participa: dos archivos pueden reutilizar un id con contenido distinto.
- **Conversaciones nuevas o modificadas:** cualquier cambio (un carácter de un turno, un dato del cliente, la fecha, las reglas, el prompt o el modelo) produce otra clave, y se llama al modelo. No existe riesgo de servir los hechos de otra conversación.
- **Validación al leer:** los hechos del caché se vuelven a validar contra la conversación; si no cuadran, se ignoran y se llama al modelo.
- **Tolerante a fallos:** si la base no responde, la auditoría sigue con el modelo.
- **Por qué:** la cuota gratuita del modelo es de 20 llamadas diarias. Sin caché, auditar el mismo archivo dos veces en un día (por ejemplo, la generación de `results.json` y la verificación de un evaluador) agotaría la cuota y la segunda ejecución saldría parcial. Con caché, repetir un archivo ya auditado es instantáneo, gratuito y da exactamente el mismo resultado. Una ejecución interrumpida por la cuota se completa más tarde gastando solo las llamadas faltantes.
- **Transparencia:** cada auditoría indica `facts_origin` y cada ejecución `facts_origin_distribution`.

## Estrategia de pruebas

- **Tests golden:** con los hechos anotados a mano para las 20 conversaciones, el motor reproduce exactamente la evaluación manual (criterios fallidos y severidad). Aíslan la lógica determinista: si fallan, el error está en un criterio, no en el modelo.
- **Tests unitarios:** montos y fechas en español, modo degradado, validación de hechos, puntaje, reporte, reintentos del adaptador de Gemini (con objetos reales del SDK y sin red) y todos los endpoints.
- **Tests de integración:** el repositorio de Postgres contra una base real y migrada (se activan con `TEST_DATABASE_URL`).
- **Stack local:** `docker compose up` levanta la imagen de producción y un Postgres con las migraciones. El proveedor `replay` permite probar el flujo completo sin clave de LLM.
- **Medición de precisión:** `scripts/evaluate_precision.py` compara los veredictos de una ejecución guardada (`results.json`) con la evaluación manual y reporta precisión, recall, F1, coincidencias exactas y de severidad, sin volver a llamar al modelo. `scripts/evaluate_extraction.py` permite, además, diagnosticar la extracción del modelo campo por campo (consume cuota).

## Limitaciones conocidas

- **Rúbrica específica del agente.** Los criterios están diseñados para las reglas de Lina. El endpoint acepta otra especificación de agente (se usa como contexto del prompt), pero los criterios no cambian.
- **Juicio subjetivo en casos límite.** El tono (R10.b) y la frontera entre anunciar un reclamo y presentarlo (R7, conversación C09, la única discrepancia con la evaluación manual) dependen de interpretación; dos evaluadores humanos también podrían discrepar.
- **Validación con una sola anotación.** La evaluación de referencia la hizo una sola persona sobre 20 conversaciones. Es suficiente para detectar regresiones, no para estimar la precisión con intervalos de confianza estrechos.
- **Formatos de fecha y monto no cubiertos.** Fechas con el día en palabras ("quince de septiembre") o montos con decimales ("1,5 millones") no se reconocen. En esos casos el criterio falla por "no mencionó la fecha" o compara contra otro valor. Todas las formas presentes en el dataset están cubiertas por tests.
- **Transcripción como verdad.** Se asume que la transcripción es correcta; los errores del reconocimiento de voz se trasladan a la evaluación.
- **No determinismo residual.** Se usa la temperatura por defecto del modelo, porque Google desaconseja bajarla en Gemini 3. En casos ambiguos, el modelo puede variar entre ejecuciones. Los criterios de código no varían, y la validación de turnos contra la transcripción acota el margen de error.
- **Lote síncrono.** Evaluar 20 conversaciones nuevas respetando 4 llamadas por minuto toma unos 5 a 7 minutos en una sola petición HTTP (desde el caché, segundos). Para volúmenes mayores convendría un procesamiento asíncrono con cola.
- **Disponibilidad del proveedor.** El modelo puede responder 503 por alta demanda en momentos puntuales; el servicio reintenta con backoff y, si persiste, entrega esa conversación como parcial con la causa.
- **Sin autenticación.** La API es pública, como pide el ejercicio. El gasto se acota con un presupuesto diario de llamadas al modelo y un límite por IP (ver [despliegue.md](despliegue.md)); en producción real se agregaría autenticación y límites por cliente identificado.
- **Cuota del modelo para conversaciones nuevas.** El caché solo evita llamadas para conversaciones ya analizadas. Con el tier gratuito (20 llamadas diarias en este proyecto), un lote grande de conversaciones nuevas se completa parcialmente y requiere repetirse tras la renovación de la cuota o pasar al tier de pago.
- **Pausa de la base gratuita.** Supabase pausa los proyectos gratuitos tras una semana sin actividad. Auditar sigue funcionando (con `persisted: false`), pero las consultas de auditorías guardadas responden 503 hasta reactivar el proyecto.
- **Arranque en frío.** En el plan gratuito de la plataforma de despliegue, la primera petición después de un periodo sin tráfico puede tardar cerca de un minuto.
