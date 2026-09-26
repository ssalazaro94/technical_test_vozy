"""R9 (closing) and R10 (respectful conduct, no legal threats)."""

from callaudit.domain.audit import Method, Severity
from callaudit.domain.criteria.base import (
    AuditContext,
    Criterion,
    Finding,
    complies,
    violates,
)


def _summarizes_outcome(ctx: AuditContext) -> Finding:
    turn = ctx.facts.closing_summary_turn
    if turn is not None:
        return complies("Cerró con un resumen del resultado o de la gestión registrada.", turn)
    return violates(
        "La llamada terminó sin un resumen del resultado ni de la gestión registrada.",
        ctx.last_agent_turn,
    )


def _says_goodbye(ctx: AuditContext) -> Finding:
    turn = ctx.facts.farewell_turn
    if turn is not None:
        return complies("Se despidió del cliente.", turn)
    return violates("La llamada terminó sin una despedida del agente.", ctx.last_agent_turn)


def _no_legal_threats(ctx: AuditContext) -> Finding:
    # Union of the code lexicon and the model: R10 forbids even mentioning these
    # actions, so the lexicon alone is enough to fail; the model adds paraphrases.
    model_turns = ctx.facts.legal_threat_turns if ctx.has_facts else []
    turns = sorted({*ctx.legal_action_turns, *model_turns})
    if turns:
        return violates(
            "Mencionó acciones legales, embargos o reportes a centrales de riesgo, lo cual está "
            "prohibido.",
            *turns,
        )
    return complies("No mencionó acciones legales, embargos ni reportes a centrales de riesgo.")


def _respectful_tone(ctx: AuditContext) -> Finding:
    # Legal threats are already penalized by R10.a; counting them again here
    # would punish the same sentence twice.
    already_counted = {*ctx.legal_action_turns, *ctx.facts.legal_threat_turns}
    turns = [turn for turn in ctx.facts.pressure_turns if turn not in already_counted]
    if turns:
        return violates(
            "Presionó al cliente o ignoró lo que acababa de decir, en lugar de mantener un trato "
            "empático.",
            *turns,
        )
    if ctx.facts.pressure_turns:
        return complies(
            "La única presión detectada fue la mención de acciones legales, ya penalizada en "
            "R10.a; fuera de eso el trato fue respetuoso."
        )
    return complies("Mantuvo un trato respetuoso y empático, sin presionar.")


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        id="R9.a",
        rule_id="R9",
        title="Cierra con un resumen del resultado (compromiso o gestión registrada)",
        severity=Severity.MINOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_summarizes_outcome,
    ),
    Criterion(
        id="R9.b",
        rule_id="R9",
        title="Se despide del cliente",
        severity=Severity.MINOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_says_goodbye,
    ),
    Criterion(
        id="R10.a",
        rule_id="R10",
        title="No menciona acciones legales, embargos ni reportes a centrales de riesgo",
        severity=Severity.CRITICAL,
        method=Method.HYBRID,
        requires_facts=False,
        evaluate=_no_legal_threats,
    ),
    Criterion(
        id="R10.b",
        rule_id="R10",
        title="Mantiene un tono respetuoso y empático, sin presionar",
        severity=Severity.MAJOR,
        method=Method.LLM,
        requires_facts=True,
        evaluate=_respectful_tone,
    ),
)
