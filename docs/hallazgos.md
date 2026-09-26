# Hallazgos: calidad del agente Lina

**Para:** equipo de cobranza de Banco Andino
**Alcance:** 20 llamadas salientes de cobranza, evaluadas contra las 10 reglas de negocio del agente (21 criterios).

## Resumen

7 de las 20 llamadas se ejecutaron sin fallas. Otras 7 tienen al menos una falla **crítica**, es decir, con riesgo regulatorio o de reputación para el banco. Las fallas se concentran en tres temas; los tres se pueden corregir con cambios de configuración, no solo de redacción del prompt.

## 1. Se revela información de la deuda sin verificar la identidad (4 de 20 llamadas)

- En dos llamadas el agente informó monto y producto sin pedir los últimos 4 dígitos del documento.
- En otra, el cliente dio dígitos que **no coincidían** (6295 frente a 6259) y el agente continuó como si fueran correctos.
- En una cuarta, quien contestó fue la esposa del titular y el agente le informó el monto y el producto.

**Recomendación.** Sacar esta decisión del prompt y convertirla en un control del flujo. Los datos de la deuda no deberían estar en el contexto del agente hasta que una función de verificación compare los dígitos contra el registro y devuelva una coincidencia exacta. Si quien atiende no es el titular, el agente debería seguir un guion cerrado que solo pida un horario de rellamada.

## 2. Presión indebida y escalamientos ignorados (3 de 20 llamadas)

- En dos llamadas el agente mencionó "centrales de riesgo", "embargo" y "cobro jurídico", expresamente prohibidos.
- En una de ellas el cliente afirmaba haber pagado en sucursal y el agente insistió dos veces en una nueva fecha de pago, sin preguntar fecha ni canal del pago ni mencionar el plazo de 48 horas.
- En otra, el cliente pidió dos veces hablar con una persona y el agente respondió pidiendo una fecha de pago; el cliente colgó.

**Recomendación.**
- Añadir un filtro de salida que bloquee y reformule cualquier respuesta con términos legales prohibidos, además de la instrucción en el prompt.
- Definir una herramienta de transferencia a asesor que se active ante cuatro intenciones: pedir un humano, disputar la deuda, sospechar fraude o reclamar un pago no reflejado.
- Crear un flujo específico para "ya pagué": pedir fecha y canal, informar el plazo de 48 horas y cerrar sin pedir un nuevo compromiso.

## 3. Negociación fuera de política y datos mal informados (5 de 20 llamadas)

- El agente ofreció un **20% de descuento**, un beneficio que no está autorizado a conceder.
- Aceptó fechas de pago fuera de la ventana permitida: una 12 días después de la llamada, otra anterior a la llamada y otra sin fecha concreta ("el sábado").
- Informó un monto distinto al registrado ($2.620.000 frente a $2.260.000) y una fecha de vencimiento equivocada. El cliente del primer caso reaccionó con sorpresa, lo que anticipa un posible reclamo.

**Recomendación.**
- Que el agente no genere montos ni fechas: el monto y la fecha de vencimiento deben insertarse desde los datos del cliente con una plantilla fija.
- Validar la fecha de pago con una función que rechace fechas vagas, pasadas o posteriores a 5 días antes de confirmar el compromiso.
- Ante pedidos de descuento, cuotas o refinanciación, usar una respuesta de plantilla que registre la solicitud y anuncie el contacto de un asesor.

## Otros ajustes menores

- **Cierre:** en 5 llamadas no hubo resumen del resultado al cerrar. Conviene fijar una plantilla de cierre que repita el monto y la fecha comprometidos, o la gestión registrada.
- **Apertura:** en una llamada el agente no se presentó como asistente virtual ni informó la grabación antes de pedir el documento. La apertura debería ser un texto fijo, no generado.

## Cómo medir la mejora

El servicio de auditoría puede ejecutarse sobre cada nueva tanda de llamadas. Sugerimos seguir semanalmente tres indicadores: el porcentaje de llamadas con falla crítica (hoy 35%), el cumplimiento de verificación de identidad (R2 y R3) y el cumplimiento de la ventana de fecha de pago (R5).
