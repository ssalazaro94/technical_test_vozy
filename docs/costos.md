# Costo estimado de evaluar 1.000 conversaciones

## Resumen

| Escenario | Costo por 1.000 conversaciones | Tiempo aproximado |
|---|---|---|
| Tier gratuito de Gemini (configuración actual) | **USD 0** | 100 minutos a 10 llamadas por minuto, sujeto al límite diario de la cuenta |
| Tier de pago, razonamiento del modelo desactivado | **~USD 1,8** | Limitado solo por la cuota de pago |
| Tier de pago, razonamiento dinámico (valor por defecto del modelo) | **~USD 6** | Limitado solo por la cuota de pago |
| Tier de pago con Batch API (50% de descuento, respuesta diferida) | **~USD 0,9 a 3** | Horas (asíncrono) |

La infraestructura (servicio web y base de datos en planes gratuitos) no agrega costo a este volumen.

## Cómo se calcula

El servicio hace **una llamada al LLM por conversación**. Los reintentos por respuestas inválidas y por errores transitorios se estiman en un 10% adicional.

### Tamaño de cada llamada (medido sobre las 20 conversaciones del dataset)

| Parte | Caracteres | Tokens estimados |
|---|---|---|
| Instrucciones del sistema (reglas del agente y criterios de interpretación) | 4.773 | ~1.200 |
| Esquema JSON de respuesta | 5.105 | ~1.300 |
| Datos del cliente y transcripción numerada (promedio; máximo 1.479) | 1.042 | ~260 |
| **Entrada total** | **~10.900** | **~2.700 (se usan 3.000 para el cálculo)** |
| Respuesta (ficha de hechos en JSON) | ~600 | ~200 (se usan 300) |
| Razonamiento interno del modelo, si está activo | variable | 0 a 2.000 (se usan 1.500) |

La conversión se hace a razón de unos 4 caracteres por token, una aproximación habitual para texto en español. Se reemplazará por el consumo real reportado por la API (`usage_metadata`) al ejecutar el servicio con la clave.

### Precios de referencia

Tarifa publicada para `gemini-2.5-flash` en el tier de pago. Debe verificarse en la página oficial de precios de Google antes de usar esta estimación, porque los precios cambian.

| Concepto | USD por millón de tokens |
|---|---|
| Entrada | 0,30 |
| Salida (incluye el razonamiento interno) | 2,50 |

### Cálculo

```
entrada   = 1.000 x 3.000 tokens = 3,0 M  x 0,30 = USD 0,90
salida    = 1.000 x   300 tokens = 0,3 M  x 2,50 = USD 0,75
subtotal sin razonamiento                     = USD 1,65  -> +10% reintentos = ~USD 1,8

razonamiento = 1.000 x 1.500 tokens = 1,5 M x 2,50 = USD 3,75
subtotal con razonamiento                      = USD 5,40 -> +10% reintentos = ~USD 5,9
```

## Tier gratuito: costo cero, pero con límites de volumen

El tier gratuito no cobra, pero limita las llamadas por minuto y por día, y los límites varían por modelo y cambian con el tiempo (se consultan en Google AI Studio). Con la configuración por defecto del servicio (10 llamadas por minuto), 1.000 conversaciones toman unos 100 minutos. Si el límite diario de la cuenta fuera, por ejemplo, de 250 llamadas, el lote tendría que repartirse en 4 días o pasar al tier de pago.

## Cómo reducir el costo

- **Desactivar o acotar el razonamiento del modelo.** La tarea es de localización y no de razonamiento largo, y es el componente más caro. Conviene medir si la precisión se mantiene con un presupuesto de razonamiento bajo.
- **Caché de contexto.** El 90% de la entrada (instrucciones y esquema) es idéntico en todas las llamadas. Los modelos 2.5 aplican descuento sobre los tokens repetidos que quedan en caché.
- **Batch API.** Para auditorías no urgentes (por ejemplo, nocturnas), la API por lotes cuesta la mitad.
- **Más de una conversación por llamada.** Reduciría las instrucciones repetidas, a costa de respuestas más largas y de más riesgo de confundir turnos entre conversaciones. No se recomienda sin medir antes la precisión.
