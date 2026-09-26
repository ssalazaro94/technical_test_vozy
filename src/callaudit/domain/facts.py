"""What the language model is asked to observe in a call, and nothing more.

The model never decides whether a rule was met. It only points at the turns
where things happened ("the agent disclosed the debt in turn 4"). Verdicts are
computed from these pointers by deterministic code, and quotes are copied from
the transcript by index, so they cannot be invented.

Every turn pointer is annotated with the speaker it must belong to. That lets
`inconsistencies()` reject a hallucinated or shifted index before it reaches a
verdict.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from callaudit.domain.conversation import Conversation, Speaker


@dataclass(frozen=True)
class TurnOf:
    """Metadata marker: the annotated index must point to a turn by `speaker`."""

    speaker: Speaker


AgentTurn = Annotated[int | None, TurnOf(Speaker.AGENT)]
ClientTurn = Annotated[int | None, TurnOf(Speaker.CLIENT)]
AgentTurns = Annotated[list[int], TurnOf(Speaker.AGENT)]


class Interlocutor(StrEnum):
    HOLDER = "titular"
    THIRD_PARTY = "tercero"
    UNIDENTIFIED = "no_identificado"


class Outcome(StrEnum):
    PAYMENT_COMMITMENT = "compromiso_pago"
    PAYMENT_REPORTED = "pago_reportado"
    ESCALATED = "escalado_asesor"
    CALLBACK = "tercero_rellamada"
    NO_RESULT = "sin_resultado"


class _Facts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentCommitment(_Facts):
    client_proposal_turn: ClientTurn = Field(
        default=None,
        description="Turno del cliente donde propone o acepta la fecha de pago.",
    )
    agent_confirmation_turn: AgentTurn = Field(
        default=None,
        description="Turno del agente donde confirma o registra el compromiso de pago.",
    )


class ConversationFacts(_Facts):
    interlocutor: Interlocutor = Field(
        description="Quien atendió la llamada: el titular de la deuda, un tercero o no se sabe.",
    )
    interlocutor_turn: ClientTurn = Field(
        default=None,
        description="Turno del cliente donde confirma o niega ser el titular.",
    )
    debt_disclosure_turn: AgentTurn = Field(
        default=None,
        description="Primer turno del agente que revela monto, producto o fechas de la deuda.",
    )
    payment_commitment: PaymentCommitment | None = Field(
        default=None,
        description="Compromiso de pago acordado en la llamada, si existe.",
    )
    benefit_request_turn: ClientTurn = Field(
        default=None,
        description="Turno del cliente donde pide descuento, condonación, refinanciación o cuotas.",
    )
    benefit_offer_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente donde ofrece o concede descuento, condonación, refinanciación "
            "o cuotas. No cuenta cuando el agente dice que no puede ofrecerlos."
        ),
    )
    benefit_referral_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente donde registra la solicitud de beneficio e informa que un "
            "asesor contactará al cliente."
        ),
    )
    escalation_request_turn: ClientTurn = Field(
        default=None,
        description=(
            "Turno del cliente donde pide un asesor humano, presenta un reclamo o disputa la "
            "deuda (desconoce el producto, sospecha fraude). La sola sorpresa por el monto no "
            "es una disputa."
        ),
    )
    escalation_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente donde transfiere la llamada o registra el contacto con un asesor."
        ),
    )
    payment_reported_turn: ClientTurn = Field(
        default=None,
        description="Turno del cliente donde afirma que ya pagó.",
    )
    paid_details_request_turn: AgentTurn = Field(
        default=None,
        description="Turno del agente donde pregunta la fecha y el canal del pago reportado.",
    )
    reflection_delay_notice_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente donde informa que el pago puede tardar hasta 48 horas en reflejarse."
        ),
    )
    insistence_turns: AgentTurns = Field(
        default_factory=list,
        description=(
            "Turnos del agente que insisten en un nuevo compromiso después de que el cliente "
            "dijo que ya pagó."
        ),
    )
    callback_request_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente donde pide a un tercero un horario para volver a llamar al titular."
        ),
    )
    closing_summary_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente que resume el resultado: monto y fecha del compromiso, o la "
            "gestión registrada (solicitud, transferencia, rellamada)."
        ),
    )
    farewell_turn: AgentTurn = Field(
        default=None,
        description=(
            "Turno del agente donde se despide. En una transferencia, el agradecimiento "
            "previo cuenta."
        ),
    )
    legal_threat_turns: AgentTurns = Field(
        default_factory=list,
        description=(
            "Turnos del agente que mencionan acciones legales, embargos o reportes a "
            "centrales de riesgo."
        ),
    )
    pressure_turns: AgentTurns = Field(
        default_factory=list,
        description=(
            "Turnos del agente irrespetuosos, que presionan, amenazan o ignoran lo que el "
            "cliente acaba de decir."
        ),
    )
    outcome: Outcome = Field(description="Resultado de la gestión.")

    def inconsistencies(self, conversation: Conversation) -> list[str]:
        """Describe every turn pointer that is out of range or has the wrong speaker."""
        return _check_pointers(self, conversation, prefix="")


def _check_pointers(model: BaseModel, conversation: Conversation, prefix: str) -> list[str]:
    problems: list[str] = []
    last = len(conversation.transcript) - 1
    for name, field in type(model).model_fields.items():
        value: Any = getattr(model, name)
        if isinstance(value, BaseModel):
            problems.extend(_check_pointers(value, conversation, prefix=f"{prefix}{name}."))
            continue
        marker = next((meta for meta in field.metadata if isinstance(meta, TurnOf)), None)
        if marker is None or value is None:
            continue
        for index in value if isinstance(value, list) else [value]:
            label = f"{prefix}{name}={index}"
            if not 0 <= index <= last:
                problems.append(f"{label}: fuera de rango (0..{last})")
            elif conversation.transcript[index].speaker is not marker.speaker:
                problems.append(f"{label}: se esperaba un turno de '{marker.speaker}'")
    return problems
