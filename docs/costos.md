# Costo estimado de evaluar 1.000 conversaciones

Modelo: `gemini-3.8-flash`. Precios tomados de la página oficial de precios de la API de Gemini (septiembre de 2026).

## Resumen

| Escenario | Costo por 1.000 conversaciones | Tiempo aproximado |
|---|---|---|
| Tier gratuito (configuración actual) | **USD 0** | 100 minutos a 10 llamadas por minuto, sujeto al límite diario del proyecto |
| Tier de pago, razonamiento mínimo | **~USD 3,7** | Limitado solo por la cuota de pago |
| Tier de pago, razonamiento por defecto del modelo (`high`, configuración actual) | **~USD 12** | Limitado solo por la cuota de pago |
| Tier de pago con Batch API (50% de descuento, respuesta diferida) | **~USD 1,9 a 6** | Horas (asíncrono) |
| Mismos escenarios de pago desde el 1 de enero de 2027 | **~USD 7,4 a 24** | Google duplica la tarifa de este modelo en esa fecha |

La infraestructura (servicio web y base de datos en planes gratuitos) no agrega costo a este volumen.

## Cómo se calcula

El servicio hace **una llamada al LLM por conversación**. Los reintentos (por respuestas inválidas o errores transitorios) se estiman en un 10% adicional.

### Tamaño de cada llamada (medido sobre las 20 conversaciones del dataset)

| Parte | Caracteres | Tokens estimados |
|---|---|---|
| Instrucciones del sistema (reglas del agente y criterios de interpretación) | 4.773 | ~1.200 |
| Esquema JSON de respuesta | 5.105 | ~1.300 |
| Datos del cliente y transcripción numerada (promedio; máximo 1.479) | 1.042 | ~260 |
| **Entrada total** | **~10.900** | **~2.700 (se usan 3.000 para el cálculo)** |
| Respuesta (ficha de hechos en JSON) | ~600 | ~200 (se usan 300) |
| Razonamiento interno del modelo | variable | Casi nulo con nivel `minimal`; se estiman 2.000 con el nivel por defecto (`high`) |

La conversión se hace a razón de unos 4 caracteres por token, una aproximación habitual para texto en español. Se reemplazará por el consumo real que reporta la API (`usage_metadata`) al ejecutar el servicio con la clave.

### Precios oficiales de `gemini-3.8-flash` (tier de pago, USD por millón de tokens)

| Concepto | Hasta el 31-dic-2026 | Desde el 1-ene-2027 | Batch hasta el 31-dic-2026 |
|---|---|---|---|
| Entrada | 0,75 | 1,50 | 0,375 |
| Salida (incluye el razonamiento interno) | 3,75 | 7,50 | 1,875 |

### Cálculo (tarifa vigente)

```
entrada      = 1.000 x 3.000 tokens = 3,0 M x 0,75 = USD 2,25
salida       = 1.000 x   300 tokens = 0,3 M x 3,75 = USD 1,13
subtotal con razonamiento mínimo               = USD 3,38 -> +10% reintentos = ~USD 3,7

razonamiento = 1.000 x 2.000 tokens = 2,0 M x 3,75 = USD 7,50
subtotal con razonamiento por defecto          = USD 10,88 -> +10% reintentos = ~USD 12
```

## Tier gratuito: costo cero, pero con límites de volumen

El tier gratuito no cobra: da una cuota de llamadas por minuto y por día, por proyecto, que se reinicia a la medianoche del Pacífico. Los límites varían por modelo y se consultan en Google AI Studio. Con la configuración por defecto del servicio (10 llamadas por minuto), 1.000 conversaciones toman unos 100 minutos. Si el límite diario fuera menor que el volumen, el lote tendría que repartirse en varios días o pasar al tier de pago.

## Cómo reducir el costo

- **Bajar el nivel de razonamiento** (`thinking_level`: `minimal`, `low` o `medium`). Es la palanca principal: el razonamiento se cobra como salida, que es el componente más caro. La tarea es de localización, no de razonamiento largo, pero conviene medir si la precisión se mantiene antes de bajarlo.
- **Un modelo más liviano.** `gemini-3.5-flash-lite` cuesta USD 0,30 y 2,50 por millón (entrada y salida): unos USD 1,8 por 1.000 conversaciones con razonamiento mínimo. Habría que validar su precisión con el script de evaluación.
- **Caché de contexto.** Cerca del 90% de la entrada (instrucciones y esquema) es idéntica en todas las llamadas. La caché cobra menos por esos tokens repetidos.
- **Batch API.** Para auditorías no urgentes (por ejemplo, nocturnas), la API por lotes cuesta la mitad.
- **Más de una conversación por llamada.** Reduciría las instrucciones repetidas, a costa de respuestas más largas y de más riesgo de confundir turnos entre conversaciones. No se recomienda sin medir antes la precisión.
