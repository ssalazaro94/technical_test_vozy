"""Swagger examples built on a synthetic call, not taken from the client's dataset.

The call deliberately breaks R6 (it offers installments), so "Try it out"
shows a failed criterion with its quote.
"""

from typing import Any

from callaudit.application.agent_spec import LINA_AGENT_SPEC

SYNTHETIC_CONVERSATION: dict[str, Any] = {
    "id": "EJ01",
    "fecha_llamada": "2026-09-24",
    "datos_cliente": {
        "nombre": "Laura Beltrán",
        "ultimos4_documento": "7310",
        "producto": "Tarjeta de crédito",
        "monto_vencido_cop": 540000,
        "fecha_vencimiento": "2026-09-18",
    },
    "transcripcion": [
        {
            "hablante": "agente",
            "texto": "Buenas tardes, le habla Lina, asistente virtual de Banco Andino. Esta "
            "llamada está siendo grabada. ¿Hablo con Laura Beltrán?",
        },
        {"hablante": "cliente", "texto": "Sí, soy yo."},
        {
            "hablante": "agente",
            "texto": "Gracias, Laura. ¿Me confirma los últimos cuatro dígitos de su documento?",
        },
        {"hablante": "cliente", "texto": "7310."},
        {
            "hablante": "agente",
            "texto": "Gracias. Su tarjeta de crédito tiene un saldo vencido de quinientos "
            "cuarenta mil pesos, con vencimiento el 18 de septiembre. ¿Cuándo podría pagar?",
        },
        {"hablante": "cliente", "texto": "¿Lo puedo pagar en dos cuotas?"},
        {
            "hablante": "agente",
            "texto": "Claro, podemos dividirlo en dos cuotas de doscientos setenta mil pesos.",
        },
        {"hablante": "cliente", "texto": "Listo, pago la primera el viernes 26."},
        {
            "hablante": "agente",
            "texto": "Queda registrado su pago de doscientos setenta mil pesos para el viernes "
            "26 de septiembre. Gracias, Laura, que tenga buena tarde.",
        },
    ],
}

AGENT_SPEC_EXAMPLE: dict[str, Any] = LINA_AGENT_SPEC.model_dump(by_alias=True, mode="json")

CONVERSATION_REQUEST_EXAMPLES: dict[str, Any] = {
    "con_especificacion_por_defecto": {
        "summary": "Solo la conversación (se usa la especificación de Lina)",
        "value": {"conversacion": SYNTHETIC_CONVERSATION},
    },
    "con_especificacion_explicita": {
        "summary": "Conversación y especificación del agente",
        "value": {
            "conversacion": SYNTHETIC_CONVERSATION,
            "especificacion_agente": AGENT_SPEC_EXAMPLE,
        },
    },
}

DATASET_REQUEST_EXAMPLES: dict[str, Any] = {
    "dataset_minimo": {
        "summary": "Mismo formato que el archivo del cliente, con una conversación",
        "value": {
            "descripcion": "Ejemplo sintético",
            "especificacion_agente": AGENT_SPEC_EXAMPLE,
            "conversaciones": [SYNTHETIC_CONVERSATION],
        },
    },
}
