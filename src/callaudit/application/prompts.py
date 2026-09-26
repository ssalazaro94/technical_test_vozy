"""Prompts for fact extraction.

The prompt asks the model to locate facts, never to judge them. The JSON
schema sent alongside carries the per-field definitions (field descriptions in
`ConversationFacts`); this text adds the interpretation criteria that apply
across fields.
"""

from collections.abc import Sequence

from callaudit.domain.conversation import AgentSpec, Conversation
from callaudit.domain.text.numbers import format_cop

_SYSTEM_TEMPLATE = """\
Eres analista de calidad de llamadas de cobranza. Tu única tarea es LOCALIZAR hechos \
en una transcripción y devolverlos en JSON según el esquema. No decides si el agente \
cumple o incumple las reglas: otro sistema lo decide a partir de tus respuestas.

# Agente evaluado
- Nombre: {agent_name}
- Empresa: {company}
- Canal: {channel}
- Objetivo: {goal}

# Reglas del agente (contexto para saber qué buscar)
{rules}

# Cómo responder
- Los turnos están numerados como [n], empezando en 0. Cada campo terminado en \
"_turn" es el número del turno donde ocurre el hecho, o null si no ocurre.
- Cada campo indica si el turno debe ser del agente o del cliente. Nunca uses turnos \
del hablante "sistema".
- Si el hecho ocurre varias veces, usa el primer turno. En los campos que son listas, \
incluye todos los turnos.
- Si dudas, usa null. No supongas hechos que no estén en el texto.
- No conviertas montos ni fechas: solo indica dónde se dijeron.

# Criterios de interpretación
- interlocutor: "titular" si quien atiende confirma ser la persona buscada; \
"tercero" si dice ser otra persona; "no_identificado" si nunca se aclara.
- debt_disclosure_turn: primer turno del agente que menciona monto, producto o fechas \
de la deuda, sin importar quién atendió.
- payment_commitment: solo si el cliente propone o acepta pagar en una fecha, aunque \
sea vaga ("el sábado"). client_proposal_turn es donde el cliente la dice o la acepta; \
agent_confirmation_turn es donde el agente la registra o confirma, o null si no lo hace.
- benefit_offer_turn: el agente ofrece o concede descuento, condonación, refinanciación \
o cuotas. Decir que NO puede ofrecerlos no cuenta como oferta.
- escalation_request_turn: el cliente pide hablar con una persona o asesor, presenta un \
reclamo, desconoce el producto o sospecha fraude. La sola sorpresa por el monto \
("¿tanto?") sin contestarlo no es una disputa.
- payment_reported_turn: el cliente afirma que ya pagó la deuda.
- insistence_turns: después de que el cliente dijo que ya pagó, turnos del agente que \
piden o proponen una nueva fecha de pago o que recomiendan pagar de nuevo.
- closing_summary_turn: turno del agente que resume el resultado (monto y fecha del \
compromiso, solicitud registrada, transferencia o rellamada). Un simple "Listo" o \
"Gracias" no es un resumen.
- farewell_turn: turno del agente con una despedida ("que tenga buen día", "hasta \
luego"). Si la llamada termina en una transferencia, el agradecimiento previo cuenta.
- legal_threat_turns: turnos del agente que mencionan acciones legales, cobro jurídico, \
embargos o reportes a centrales de riesgo, incluso si se mencionan de forma condicional.
- pressure_turns: turnos del agente que exigen una fecha después de que el cliente pidió \
un asesor, ignoran lo que el cliente acaba de decir, contradicen al cliente sin empatía \
o lo amenazan.
- outcome: "compromiso_pago", "pago_reportado", "escalado_asesor", "tercero_rellamada" o \
"sin_resultado", según cómo terminó la gestión.
"""

_USER_TEMPLATE = """\
# Datos del cliente registrados por el banco
- Nombre: {name}
- Últimos 4 dígitos del documento: {last4}
- Producto: {product}
- Monto vencido: {amount}
- Fecha de vencimiento: {due_date}

# Fecha de la llamada
{call_date}

# Transcripción
{transcript}
"""

_FEEDBACK_TEMPLATE = """
# Corrige tu respuesta anterior
Tu respuesta anterior tenía estos problemas. Revisa los números de turno y el hablante \
de cada uno:
{problems}
"""


def build_system_prompt(spec: AgentSpec) -> str:
    return _SYSTEM_TEMPLATE.format(
        agent_name=spec.agent_name,
        company=spec.company,
        channel=spec.channel,
        goal=spec.goal,
        rules="\n".join(f"- {rule}" for rule in spec.rules),
    )


def render_transcript(conversation: Conversation) -> str:
    return "\n".join(
        f"[{index}] {turn.speaker.value}: {turn.text}"
        for index, turn in enumerate(conversation.transcript)
    )


def build_user_prompt(conversation: Conversation, feedback: Sequence[str] = ()) -> str:
    customer = conversation.customer
    prompt = _USER_TEMPLATE.format(
        name=customer.name,
        last4=customer.document_last4,
        product=customer.product,
        amount=format_cop(customer.overdue_amount_cop),
        due_date=customer.due_date.isoformat(),
        call_date=conversation.call_date.isoformat(),
        transcript=render_transcript(conversation),
    )
    if feedback:
        prompt += _FEEDBACK_TEMPLATE.format(problems="\n".join(f"- {item}" for item in feedback))
    return prompt
