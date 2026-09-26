"""R5 (valid payment date) and R6 (no unauthorized benefits)."""

from datetime import date, timedelta

from callaudit.domain.audit import Method, Severity
from callaudit.domain.criteria.base import (
    AuditContext,
    Criterion,
    Finding,
    complies,
    not_applicable,
    violates,
)
from callaudit.domain.text.dates import extract_dates, format_date_es

MAX_DAYS_TO_PAY = 5


def _committed_date(ctx: AuditContext) -> tuple[date, int] | None:
    """The concrete date of the commitment and the turn it was read from.

    The agent's confirmation wins because it is what gets registered; the
    client's proposal is the fallback. Only explicit dates count: a bare
    weekday ("el sábado") is not concrete and yields None.
    """
    commitment = ctx.facts.payment_commitment
    if commitment is None:
        return None
    for turn in (commitment.agent_confirmation_turn, commitment.client_proposal_turn):
        if turn is None:
            continue
        dates = extract_dates(
            ctx.conversation.transcript[turn].text,
            ctx.conversation.call_date,
            relative=True,
        )
        if dates:
            return dates[0], turn
    return None


def _date_is_concrete(ctx: AuditContext) -> Finding:
    commitment = ctx.facts.payment_commitment
    if commitment is None:
        return not_applicable("No se acordó un compromiso de pago.")
    resolved = _committed_date(ctx)
    if resolved is None:
        return violates(
            "El compromiso de pago quedó sin una fecha concreta (día y mes).",
            commitment.client_proposal_turn,
            commitment.agent_confirmation_turn,
        )
    committed, turn = resolved
    return complies(f"La fecha de pago acordada es concreta: {format_date_es(committed)}.", turn)


def _date_within_window(ctx: AuditContext) -> Finding:
    if ctx.facts.payment_commitment is None:
        return not_applicable("No se acordó un compromiso de pago.")
    resolved = _committed_date(ctx)
    if resolved is None:
        return not_applicable("No hay una fecha concreta que validar; ver R5.a.")
    committed, turn = resolved
    call_date = ctx.conversation.call_date
    latest = call_date + timedelta(days=MAX_DAYS_TO_PAY)
    delta = (committed - call_date).days
    if delta < 0:
        return violates(
            f"La fecha acordada ({format_date_es(committed)}) es anterior a la fecha de la "
            f"llamada ({format_date_es(call_date)}).",
            turn,
        )
    if delta > MAX_DAYS_TO_PAY:
        return violates(
            f"La fecha acordada ({format_date_es(committed)}) está {delta} días después de la "
            f"llamada; el máximo permitido es {MAX_DAYS_TO_PAY} "
            f"(hasta el {format_date_es(latest)}).",
            turn,
        )
    return complies(
        f"La fecha acordada ({format_date_es(committed)}) está dentro de la ventana permitida "
        f"({format_date_es(call_date)} a {format_date_es(latest)}).",
        turn,
    )


def _offers_no_benefit(ctx: AuditContext) -> Finding:
    facts = ctx.facts
    if facts.benefit_offer_turn is not None:
        return violates(
            "Ofreció un beneficio no autorizado (descuento, condonación, refinanciación o cuotas).",
            facts.benefit_request_turn,
            facts.benefit_offer_turn,
        )
    return complies(
        "No ofreció descuentos, condonaciones, refinanciaciones ni cuotas.",
        facts.benefit_referral_turn,
    )


def _refers_benefit_request(ctx: AuditContext) -> Finding:
    facts = ctx.facts
    if facts.benefit_request_turn is None:
        return not_applicable("El cliente no pidió descuentos, refinanciación ni cuotas.")
    if facts.benefit_offer_turn is not None:
        return violates(
            "Ante la solicitud del cliente concedió un beneficio en lugar de registrarla para "
            "un asesor.",
            facts.benefit_request_turn,
            facts.benefit_offer_turn,
        )
    if facts.benefit_referral_turn is not None:
        return complies(
            "Registró la solicitud e informó que un asesor contactará al cliente.",
            facts.benefit_request_turn,
            facts.benefit_referral_turn,
        )
    return violates(
        "No registró la solicitud del cliente ni informó que un asesor lo contactaría.",
        facts.benefit_request_turn,
        ctx.next_agent_turn(facts.benefit_request_turn),
    )


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        id="R5.a",
        rule_id="R5",
        title="La fecha de pago acordada es una fecha concreta",
        severity=Severity.MAJOR,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_date_is_concrete,
    ),
    Criterion(
        id="R5.b",
        rule_id="R5",
        title="La fecha de pago no es anterior a la llamada ni posterior a 5 días calendario",
        severity=Severity.MAJOR,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_date_within_window,
    ),
    Criterion(
        id="R6.a",
        rule_id="R6",
        title="No ofrece descuentos, condonaciones, refinanciaciones ni cuotas",
        severity=Severity.CRITICAL,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_offers_no_benefit,
    ),
    Criterion(
        id="R6.b",
        rule_id="R6",
        title="Ante una solicitud de beneficio, la registra e informa que un asesor contactará",
        severity=Severity.MAJOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_refers_benefit_request,
    ),
)
