"""Runs the rubric over one conversation and assembles its audit."""

from collections.abc import Sequence

from callaudit.domain.audit import (
    AnalysisStatus,
    ConversationAudit,
    CriterionResult,
    Evidence,
    Status,
)
from callaudit.domain.conversation import Conversation
from callaudit.domain.criteria import RUBRIC, AuditContext, Criterion, Finding
from callaudit.domain.facts import ConversationFacts
from callaudit.domain.scoring import overall_severity, weighted_score

_UNDETERMINED = Finding(
    Status.UNDETERMINED,
    "No se obtuvo el análisis del modelo de lenguaje; el criterio queda sin evaluar.",
)


def _evidence(conversation: Conversation, turns: Sequence[int]) -> list[Evidence]:
    return [
        Evidence(
            turn=turn,
            speaker=conversation.transcript[turn].speaker,
            quote=conversation.transcript[turn].text,
        )
        for turn in turns
    ]


def _run(criterion: Criterion, ctx: AuditContext) -> CriterionResult:
    finding = (
        _UNDETERMINED if criterion.requires_facts and not ctx.has_facts else criterion.evaluate(ctx)
    )
    return CriterionResult(
        criterion_id=criterion.id,
        rule_id=criterion.rule_id,
        title=criterion.title,
        method=criterion.method,
        severity=criterion.severity,
        status=finding.status,
        evidence=_evidence(ctx.conversation, finding.turns),
        explanation=finding.explanation,
    )


def audit_conversation(
    conversation: Conversation,
    facts: ConversationFacts | None,
    *,
    warnings: Sequence[str] = (),
    rubric: Sequence[Criterion] = RUBRIC,
) -> ConversationAudit:
    """Apply every criterion to the conversation.

    `facts=None` means the language model analysis failed: the criteria that
    only need code still run, the rest are marked "indeterminado", and the
    audit is flagged as partial instead of failing.
    """
    if facts is not None and (problems := facts.inconsistencies(conversation)):
        raise ValueError("inconsistent facts: " + "; ".join(problems))
    ctx = AuditContext(conversation, facts)
    results = [_run(criterion, ctx) for criterion in rubric]
    return ConversationAudit(
        conversation_id=conversation.id,
        call_date=conversation.call_date,
        analysis=AnalysisStatus.COMPLETE if facts is not None else AnalysisStatus.PARTIAL,
        outcome=facts.outcome if facts is not None else None,
        score=weighted_score(results),
        severity=overall_severity(results),
        failed_criteria=[r.criterion_id for r in results if r.status is Status.VIOLATES],
        criteria=results,
        warnings=list(warnings),
    )
