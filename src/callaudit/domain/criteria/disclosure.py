"""R3 (no disclosure to third parties) and R4 (exact amount and due date)."""

from callaudit.domain.audit import Method, Severity
from callaudit.domain.criteria.base import (
    AuditContext,
    Criterion,
    Finding,
    complies,
    not_applicable,
    violates,
)
from callaudit.domain.facts import Interlocutor
from callaudit.domain.text.dates import extract_dates, format_date_es
from callaudit.domain.text.normalize import fold
from callaudit.domain.text.numbers import extract_amounts, format_cop


def _reveals_debt(ctx: AuditContext, turn: int) -> bool:
    """Code-side detector: amount, product name or due date spoken in the turn."""
    customer = ctx.conversation.customer
    raw = ctx.conversation.transcript[turn].text
    return (
        bool(extract_amounts(raw))
        or fold(customer.product) in ctx.text(turn)
        or customer.due_date in extract_dates(raw, ctx.conversation.call_date)
    )


def _no_disclosure_to_third_party(ctx: AuditContext) -> Finding:
    facts = ctx.facts
    if facts.interlocutor is not Interlocutor.THIRD_PARTY:
        return not_applicable("Atendió el titular.")
    since = facts.interlocutor_turn if facts.interlocutor_turn is not None else -1
    leaks = {turn for turn in ctx.agent_turns if turn > since and _reveals_debt(ctx, turn)}
    if facts.debt_disclosure_turn is not None:
        leaks.add(facts.debt_disclosure_turn)
    if leaks:
        return violates(
            "Reveló información de la deuda (monto, producto o fechas) a una persona que no "
            "es el titular.",
            facts.interlocutor_turn,
            *leaks,
        )
    return complies(
        "No reveló información de la deuda a la persona que atendió.",
        facts.interlocutor_turn,
    )


def _asks_callback_time(ctx: AuditContext) -> Finding:
    facts = ctx.facts
    if facts.interlocutor is not Interlocutor.THIRD_PARTY:
        return not_applicable("Atendió el titular.")
    if facts.callback_request_turn is not None:
        return complies(
            "Solicitó un horario para volver a llamar al titular.",
            facts.callback_request_turn,
        )
    return violates(
        "No solicitó un horario para volver a llamar al titular.",
        facts.interlocutor_turn,
        ctx.last_agent_turn,
    )


def _disclosure_turn(ctx: AuditContext) -> int | Finding:
    """Shared guard for R4: the turn where the debt was stated, or why R4 does not apply."""
    facts = ctx.facts
    if facts.interlocutor is Interlocutor.THIRD_PARTY:
        return not_applicable("No corresponde informar la deuda a un tercero; ver R3.")
    if facts.debt_disclosure_turn is None:
        return not_applicable("La llamada no llegó a informar la deuda.")
    return facts.debt_disclosure_turn


def _states_exact_amount(ctx: AuditContext) -> Finding:
    turn = _disclosure_turn(ctx)
    if isinstance(turn, Finding):
        return turn
    expected = ctx.conversation.customer.overdue_amount_cop
    stated = extract_amounts(ctx.conversation.transcript[turn].text)
    if expected in stated:
        return complies(
            f"Informó el monto vencido de {format_cop(expected)}, igual al registrado.", turn
        )
    if not stated:
        return violates("Al informar la deuda no mencionó el monto vencido.", turn)
    return violates(
        f"Informó {format_cop(stated[0])}, pero el monto vencido registrado es "
        f"{format_cop(expected)}.",
        turn,
    )


def _states_exact_due_date(ctx: AuditContext) -> Finding:
    turn = _disclosure_turn(ctx)
    if isinstance(turn, Finding):
        return turn
    expected = ctx.conversation.customer.due_date
    stated = extract_dates(ctx.conversation.transcript[turn].text, ctx.conversation.call_date)
    if expected in stated:
        return complies(
            f"Informó la fecha de vencimiento {format_date_es(expected)}, igual a la registrada.",
            turn,
        )
    if not stated:
        return violates("Al informar la deuda no mencionó la fecha de vencimiento.", turn)
    return violates(
        f"Informó como fecha de vencimiento el {format_date_es(stated[0])}, pero la registrada "
        f"es el {format_date_es(expected)}.",
        turn,
    )


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        id="R3.a",
        rule_id="R3",
        title="No revela monto, producto ni fechas de la deuda a un tercero",
        severity=Severity.CRITICAL,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_no_disclosure_to_third_party,
    ),
    Criterion(
        id="R3.b",
        rule_id="R3",
        title="Solicita a un tercero un horario para volver a llamar",
        severity=Severity.MINOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_asks_callback_time,
    ),
    Criterion(
        id="R4.a",
        rule_id="R4",
        title="Informa el monto vencido exactamente como figura en los datos del cliente",
        severity=Severity.MAJOR,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_states_exact_amount,
    ),
    Criterion(
        id="R4.b",
        rule_id="R4",
        title="Informa la fecha de vencimiento exactamente como figura en los datos del cliente",
        severity=Severity.MAJOR,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_states_exact_due_date,
    ),
)
