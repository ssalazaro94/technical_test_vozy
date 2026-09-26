"""R1 (presentation and recording notice) and R2 (identity verification)."""

import re

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
from callaudit.domain.text import lexicon
from callaudit.domain.text.normalize import fold


def _first_opening_turn_matching(ctx: AuditContext, pattern: re.Pattern[str]) -> int | None:
    return next((turn for turn in ctx.opening_turns if pattern.search(ctx.text(turn))), None)


def _presents_as_lina(ctx: AuditContext) -> Finding:
    required = (
        ("el nombre Lina", lexicon.AGENT_NAME),
        ("que es asistente virtual", lexicon.VIRTUAL_ASSISTANT),
        ("Banco Andino", lexicon.COMPANY_NAME),
    )
    found = {label: _first_opening_turn_matching(ctx, pattern) for label, pattern in required}
    missing = [label for label, turn in found.items() if turn is None]
    first_turn = ctx.agent_turns[0] if ctx.agent_turns else None
    if missing:
        return violates(
            "Antes de pedir datos o informar la deuda no mencionó " + ", ni ".join(missing) + ".",
            first_turn,
            ctx.sensitive_turn,
        )
    return complies(
        "Se presentó como Lina, asistente virtual de Banco Andino, antes de pedir datos.",
        *found.values(),
    )


def _announces_recording(ctx: AuditContext) -> Finding:
    turn = _first_opening_turn_matching(ctx, lexicon.RECORDING_NOTICE)
    if turn is None:
        return violates(
            "No informó que la llamada estaba siendo grabada antes de pedir datos o informar "
            "la deuda.",
            ctx.agent_turns[0] if ctx.agent_turns else None,
            ctx.sensitive_turn,
        )
    return complies("Informó que la llamada está siendo grabada.", turn)


def _confirms_full_name(ctx: AuditContext) -> Finding:
    full_name = fold(ctx.conversation.customer.name)
    asked = next((turn for turn in ctx.agent_turns if full_name in ctx.text(turn)), None)
    if asked is None:
        return violates(
            f"Nunca confirmó el nombre completo del titular ({ctx.conversation.customer.name}).",
            ctx.agent_turns[0] if ctx.agent_turns else None,
        )
    reply = ctx.facts.interlocutor_turn if ctx.has_facts else None
    return complies("Confirmó el nombre completo del titular.", asked, reply)


def _verifies_before_disclosure(ctx: AuditContext) -> Finding:
    facts = ctx.facts
    if facts.interlocutor is Interlocutor.THIRD_PARTY:
        return not_applicable(
            "Atendió un tercero; la protección de la información se evalúa en R3."
        )
    disclosure = facts.debt_disclosure_turn
    if disclosure is None:
        return not_applicable(
            "No se reveló información de la deuda, así que no había nada que proteger."
        )
    request = ctx.digits_request_turn
    if request is not None and request < disclosure:
        return complies(
            "Solicitó los últimos 4 dígitos del documento antes de informar la deuda.",
            request,
            disclosure,
        )
    return violates(
        "Informó la deuda sin haber solicitado antes los últimos 4 dígitos del documento.",
        disclosure,
    )


def _discloses_only_if_digits_match(ctx: AuditContext) -> Finding:
    answer = ctx.digits_answer_turn
    if answer is None:
        return not_applicable("El cliente no entregó dígitos del documento.")
    expected = ctx.conversation.customer.document_last4
    given = ctx.provided_digits
    if given[-4:] == expected and len(given) >= 4:
        return complies(
            f"Los dígitos entregados ({given}) coinciden con el documento registrado.", answer
        )
    disclosure = ctx.facts.debt_disclosure_turn
    if disclosure is None or disclosure < answer:
        return complies(
            "Los dígitos entregados no coinciden y el agente no reveló información de la deuda "
            "después de recibirlos.",
            answer,
        )
    return violates(
        f"El cliente dio los dígitos {given} y el documento registrado termina en {expected}; "
        "aun así el agente informó la deuda.",
        answer,
        disclosure,
    )


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        id="R1.a",
        rule_id="R1",
        title="Se presenta como Lina, asistente virtual de Banco Andino, antes de pedir datos",
        severity=Severity.MINOR,
        method=Method.CODE,
        requires_facts=False,
        evaluate=_presents_as_lina,
    ),
    Criterion(
        id="R1.b",
        rule_id="R1",
        title="Informa que la llamada está siendo grabada antes de pedir datos",
        severity=Severity.MAJOR,
        method=Method.CODE,
        requires_facts=False,
        evaluate=_announces_recording,
    ),
    Criterion(
        id="R2.a",
        rule_id="R2",
        title="Confirma el nombre completo del titular",
        severity=Severity.MINOR,
        method=Method.CODE,
        requires_facts=False,
        evaluate=_confirms_full_name,
    ),
    Criterion(
        id="R2.b",
        rule_id="R2",
        title="Solicita los últimos 4 dígitos del documento antes de revelar la deuda",
        severity=Severity.CRITICAL,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_verifies_before_disclosure,
    ),
    Criterion(
        id="R2.c",
        rule_id="R2",
        title="Solo revela la deuda si los dígitos coinciden con el registro",
        severity=Severity.CRITICAL,
        method=Method.HYBRID,
        requires_facts=True,
        evaluate=_discloses_only_if_digits_match,
    ),
)
