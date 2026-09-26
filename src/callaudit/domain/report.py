"""Aggregate report over a set of audited conversations."""

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from callaudit.domain.audit import AnalysisStatus, ConversationAudit, Severity, Status
from callaudit.domain.criteria import RUBRIC, Criterion
from callaudit.domain.facts import Outcome

DEFAULT_TOP_FAILURES = 5


class _ReportModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class CriterionStats(_ReportModel):
    criterion_id: str
    rule_id: str
    title: str
    severity: Severity
    complied: int
    violated: int
    not_applicable: int
    undetermined: int
    compliance_rate: float | None = Field(
        description="cumple / (cumple + no_cumple), entre 0 y 1; nulo si nunca aplicó.",
    )
    failing_conversations: list[str]


class FrequentFailure(_ReportModel):
    criterion_id: str
    title: str
    severity: Severity
    occurrences: int
    share_of_conversations: float = Field(description="Fracción de conversaciones con esta falla.")
    conversations: list[str]


class DatasetReport(_ReportModel):
    total_conversations: int
    fully_analyzed: int
    average_score: float
    severity_distribution: dict[Severity, int]
    outcome_distribution: dict[Outcome, int]
    criteria: list[CriterionStats]
    most_frequent_failures: list[FrequentFailure]


def _criterion_stats(criterion: Criterion, audits: Sequence[ConversationAudit]) -> CriterionStats:
    statuses: Counter[Status] = Counter()
    failing: list[str] = []
    for audit in audits:
        result = next(r for r in audit.criteria if r.criterion_id == criterion.id)
        statuses[result.status] += 1
        if result.status is Status.VIOLATES:
            failing.append(audit.conversation_id)
    judged = statuses[Status.COMPLIES] + statuses[Status.VIOLATES]
    return CriterionStats(
        criterion_id=criterion.id,
        rule_id=criterion.rule_id,
        title=criterion.title,
        severity=criterion.severity,
        complied=statuses[Status.COMPLIES],
        violated=statuses[Status.VIOLATES],
        not_applicable=statuses[Status.NOT_APPLICABLE],
        undetermined=statuses[Status.UNDETERMINED],
        compliance_rate=round(statuses[Status.COMPLIES] / judged, 4) if judged else None,
        failing_conversations=failing,
    )


def build_report(
    audits: Sequence[ConversationAudit],
    *,
    rubric: Sequence[Criterion] = RUBRIC,
    top: int = DEFAULT_TOP_FAILURES,
) -> DatasetReport:
    stats = [_criterion_stats(criterion, audits) for criterion in rubric]
    total = len(audits)
    ranked = sorted(
        (s for s in stats if s.violated),
        key=lambda s: (-s.violated, -s.severity.weight, s.criterion_id),
    )
    return DatasetReport(
        total_conversations=total,
        fully_analyzed=sum(a.analysis is AnalysisStatus.COMPLETE for a in audits),
        average_score=round(sum(a.score for a in audits) / total, 1) if total else 0.0,
        severity_distribution={s: sum(a.severity is s for a in audits) for s in Severity},
        outcome_distribution=dict(Counter(a.outcome for a in audits if a.outcome is not None)),
        criteria=stats,
        most_frequent_failures=[
            FrequentFailure(
                criterion_id=s.criterion_id,
                title=s.title,
                severity=s.severity,
                occurrences=s.violated,
                share_of_conversations=round(s.violated / total, 4),
                conversations=s.failing_conversations,
            )
            for s in ranked[:top]
        ],
    )
