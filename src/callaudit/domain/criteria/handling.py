"""R7 (escalation to a human) and R8 (payment already made)."""

from callaudit.domain.audit import Method, Severity
from callaudit.domain.criteria.base import (
    AuditContext,
    Criterion,
    Finding,
    complies,
    not_applicable,
    violates,
)


def _escalates(ctx: AuditContext) -> Finding:
    facts = ctx.facts
    if facts.escalation_request_turn is None:
        return not_applicable("El cliente no pidió un asesor ni presentó un reclamo o disputa.")
    if facts.escalation_turn is not None:
        return complies(
            "Transfirió la llamada o registró el contacto con un asesor.",
            facts.escalation_request_turn,
            facts.escalation_turn,
        )
    return violates(
        "El cliente pidió un asesor o presentó un reclamo y el agente no transfirió la llamada "
        "ni registró el contacto.",
        facts.escalation_request_turn,
        ctx.next_agent_turn(facts.escalation_request_turn),
    )


def _payment_reported(ctx: AuditContext) -> int | Finding:
    """Shared guard for R8: the turn where the client says they paid, or why R8 does not apply."""
    turn = ctx.facts.payment_reported_turn
    if turn is None:
        return not_applicable("El cliente no indicó que ya hubiera pagado.")
    return turn


def _asks_payment_details(ctx: AuditContext) -> Finding:
    reported = _payment_reported(ctx)
    if isinstance(reported, Finding):
        return reported
    asked = ctx.facts.paid_details_request_turn
    if asked is not None:
        return complies("Preguntó la fecha y el canal del pago reportado.", reported, asked)
    return violates(
        "El cliente dijo que ya pagó y el agente no preguntó la fecha ni el canal del pago.",
        reported,
        ctx.next_agent_turn(reported),
    )


def _informs_reflection_delay(ctx: AuditContext) -> Finding:
    reported = _payment_reported(ctx)
    if isinstance(reported, Finding):
        return reported
    notice = ctx.facts.reflection_delay_notice_turn
    if notice is not None:
        return complies("Informó que el pago puede tardar hasta 48 horas en reflejarse.", notice)
    return violates(
        "No informó que el pago puede tardar hasta 48 horas en reflejarse.",
        reported,
        ctx.last_agent_turn,
    )


def _does_not_insist(ctx: AuditContext) -> Finding:
    reported = _payment_reported(ctx)
    if isinstance(reported, Finding):
        return reported
    insistence = [turn for turn in ctx.facts.insistence_turns if turn > reported]
    if insistence:
        return violates(
            "Insistió en un nuevo compromiso de pago después de que el cliente dijo que ya pagó.",
            reported,
            *insistence,
        )
    return complies("No insistió en un nuevo compromiso de pago.", reported)


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        id="R7.a",
        rule_id="R7",
        title="Ante un pedido de asesor, reclamo o disputa, transfiere o registra el contacto",
        severity=Severity.MAJOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_escalates,
    ),
    Criterion(
        id="R8.a",
        rule_id="R8",
        title="Si el cliente ya pagó, pregunta la fecha y el canal del pago",
        severity=Severity.MAJOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_asks_payment_details,
    ),
    Criterion(
        id="R8.b",
        rule_id="R8",
        title="Si el cliente ya pagó, informa que puede tardar hasta 48 horas en reflejarse",
        severity=Severity.MINOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_informs_reflection_delay,
    ),
    Criterion(
        id="R8.c",
        rule_id="R8",
        title="Si el cliente ya pagó, no insiste en un nuevo compromiso",
        severity=Severity.MAJOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_does_not_insist,
    ),
)
