# API

La documentación interactiva (Swagger) está en `/docs` y el esquema OpenAPI en `/openapi.json`. La raíz `/` redirige a `/docs`.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado del servicio, modelo de lenguaje activo y versión de la rúbrica |
| GET | `/v1/rubric` | Criterios, severidades, pesos y regla de puntaje |
| POST | `/v1/audits` | Audita una conversación |
| POST | `/v1/audits/dataset` | Audita un conjunto de conversaciones enviado como JSON en el cuerpo |
| POST | `/v1/audits/dataset/file` | Igual que el anterior, pero recibe el archivo `.json` como subida multipart |

## Auditar una conversación

`POST /v1/audits`

```json
{
  "conversacion": {
    "id": "EJ01",
    "fecha_llamada": "2026-09-24",
    "datos_cliente": {
      "nombre": "Laura Beltrán",
      "ultimos4_documento": "7310",
      "producto": "Tarjeta de crédito",
      "monto_vencido_cop": 540000,
      "fecha_vencimiento": "2026-09-18"
    },
    "transcripcion": [
      {"hablante": "agente", "texto": "Buenas tardes, le habla Lina, asistente virtual de Banco Andino. ..."},
      {"hablante": "cliente", "texto": "Sí, soy yo."}
    ]
  },
  "especificacion_agente": null
}
```

`especificacion_agente` es opcional: si se omite, se usa la especificación de Lina. Los valores válidos de `hablante` son `agente`, `cliente` y `sistema` (eventos de telefonía, como una transferencia).

Respuesta (resumida):

```json
{
  "conversation_id": "EJ01",
  "call_date": "2026-09-24",
  "analysis": "completo",
  "outcome": "compromiso_pago",
  "score": 82.2,
  "severity": "critica",
  "failed_criteria": ["R6.a", "R6.b"],
  "criteria": [
    {
      "criterion_id": "R6.a",
      "rule_id": "R6",
      "title": "No ofrece descuentos, condonaciones, refinanciaciones ni cuotas",
      "method": "llm",
      "severity": "critica",
      "status": "no_cumple",
      "evidence": [
        {"turn": 5, "speaker": "cliente", "quote": "¿Lo puedo pagar en dos cuotas?"},
        {"turn": 6, "speaker": "agente", "quote": "Claro, podemos dividirlo en dos cuotas de doscientos setenta mil pesos."}
      ],
      "explanation": "Ofreció un beneficio no autorizado (descuento, condonación, refinanciación o cuotas)."
    }
  ],
  "warnings": []
}
```

| Campo | Descripción |
|---|---|
| `analysis` | `completo`, o `parcial` si el modelo de lenguaje no estuvo disponible |
| `outcome` | Resultado de la gestión: `compromiso_pago`, `pago_reportado`, `escalado_asesor`, `tercero_rellamada`, `sin_resultado`. Es `null` en análisis parcial |
| `score` | 0 a 100, ponderado por severidad (ver [rubrica.md](rubrica.md)) |
| `severity` | `ninguna`, `leve`, `grave` o `critica` |
| `criteria[].status` | `cumple`, `no_cumple`, `no_aplica` o `indeterminado` |
| `criteria[].evidence` | Turnos citados de forma literal; `turn` es el índice en la transcripción, desde 0 |
| `warnings` | Causa de la degradación, si la hubo |

Todas las auditorías tienen exactamente la misma estructura, incluso las parciales, y siempre incluyen los 21 criterios en el mismo orden.

## Auditar un conjunto de conversaciones

`POST /v1/audits/dataset` recibe el mismo formato del archivo del cliente:

```json
{
  "descripcion": "...",
  "especificacion_agente": {"nombre_agente": "Lina", "empresa": "...", "canal": "...", "objetivo": "...", "reglas": ["R1. ...", "R2. ..."]},
  "conversaciones": [ ... ]
}
```

`POST /v1/audits/dataset/file` recibe ese mismo contenido como archivo:

```bash
curl -F "file=@/ruta/al/dataset.json;type=application/json" \
  https://<servicio>/v1/audits/dataset/file
```

Respuesta:

```json
{
  "run_id": "5f0c...",
  "generated_at": "2026-09-25T20:15:03Z",
  "rubric_version": "2026-09-25",
  "model": "gemini-2.5-flash",
  "report": {
    "total_conversations": 20,
    "fully_analyzed": 20,
    "average_score": 89.3,
    "severity_distribution": {"ninguna": 7, "leve": 1, "grave": 5, "critica": 7},
    "outcome_distribution": {"compromiso_pago": 12, "escalado_asesor": 3, "pago_reportado": 2, "sin_resultado": 2, "tercero_rellamada": 1},
    "criteria": [
      {"criterion_id": "R9.a", "complied": 15, "violated": 5, "not_applicable": 0,
       "undetermined": 0, "compliance_rate": 0.75, "failing_conversations": ["C03", "..."]}
    ],
    "most_frequent_failures": [
      {"criterion_id": "R9.a", "occurrences": 5, "share_of_conversations": 0.25, "conversations": ["..."]}
    ]
  },
  "audits": [ ... ]
}
```

`compliance_rate` = cumple / (cumple + no_cumple). Es `null` si el criterio no aplicó en ninguna conversación. Las fallas más frecuentes se ordenan por número de ocurrencias y, ante un empate, por severidad.

## Errores

Todos los errores usan la misma forma:

```json
{
  "error": {
    "code": "entrada_invalida",
    "message": "La solicitud no cumple el formato esperado.",
    "details": [{"location": "body.conversacion.fecha_llamada", "message": "Field required"}]
  }
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `no_encontrado` | Ruta inexistente |
| 405 | `metodo_no_permitido` | Método HTTP no soportado en la ruta |
| 413 | `demasiado_grande` | Archivo mayor a 2 MB o más de 100 conversaciones |
| 422 | `entrada_invalida` | El cuerpo JSON no cumple el formato |
| 422 | `archivo_invalido` | El archivo no es JSON o no tiene el formato del dataset |
| 500 | `error_interno` | Error inesperado; el detalle queda en el log del servidor |

Una falla del modelo de lenguaje **no** es un error HTTP: se responde 200 con la auditoría en modo `parcial` y la causa en `warnings`.
