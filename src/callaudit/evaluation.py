"""Precision of an audit run against a manual ground truth.

The comparison works on verdicts: which criteria the service marked as failed
in each conversation, against the ones a human annotator marked. It needs no
language model call, so it can be computed from a saved run (results.json) as
many times as needed.

Definitions, per (conversation, criterion) pair:
- true positive: the service and the annotator both marked it as failed;
- false positive: only the service marked it (a false alarm);
- false negative: only the annotator marked it (a missed failure).
Precision = TP / (TP + FP): of the failures reported, how many are real.
Recall = TP / (TP + FN): of the real failures, how many were found.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from callaudit.application.models import DatasetAudit
from callaudit.domain.audit import AnalysisStatus, Severity


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class GroundTruthEntry(_EvaluationModel):
    """The manual verdict for one conversation."""

    failed: list[str]
    severity: Severity


class CriterionMetrics(_EvaluationModel):
    criterion_id: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float | None
    recall: float | None


class ConversationComparison(_EvaluationModel):
    conversation_id: str
    expected_failures: list[str]
    predicted_failures: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    expected_severity: Severity
    predicted_severity: Severity


class PrecisionReport(_EvaluationModel):
    run_id: str
    model: str
    conversations_compared: int
    skipped_partial: list[str]
    missing_from_run: list[str]
    not_in_ground_truth: list[str]
    exact_matches: int
    severity_matches: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None
    per_criterion: list[CriterionMetrics]
    mismatches: list[ConversationComparison]


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    """Harmonic mean of precision and recall; None if either is undefined."""
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 3)


def compare_run(
    run: DatasetAudit,
    ground_truth: Mapping[str, GroundTruthEntry],
    criterion_ids: Sequence[str] | None = None,
) -> PrecisionReport:
    """Compare the failed criteria of each audit with the manual verdicts.

    Partial audits (the model did not answer) are skipped and listed: they say
    nothing about the model's accuracy. Conversations present in only one side
    are listed too, never silently ignored.
    """
    audits = {audit.conversation_id: audit for audit in run.audits}
    counts: dict[str, list[int]] = {}
    comparisons: list[ConversationComparison] = []
    skipped: list[str] = []

    for conversation_id, expected in ground_truth.items():
        audit = audits.get(conversation_id)
        if audit is None:
            continue
        if audit.analysis is AnalysisStatus.PARTIAL:
            skipped.append(conversation_id)
            continue
        predicted, real = set(audit.failed_criteria), set(expected.failed)
        for criterion in predicted | real:
            tp_fp_fn = counts.setdefault(criterion, [0, 0, 0])
            tp_fp_fn[0] += criterion in predicted and criterion in real
            tp_fp_fn[1] += criterion in predicted and criterion not in real
            tp_fp_fn[2] += criterion in real and criterion not in predicted
        comparisons.append(
            ConversationComparison(
                conversation_id=conversation_id,
                expected_failures=sorted(real),
                predicted_failures=sorted(predicted),
                false_positives=sorted(predicted - real),
                false_negatives=sorted(real - predicted),
                expected_severity=expected.severity,
                predicted_severity=audit.severity,
            )
        )

    per_criterion: list[CriterionMetrics] = []
    for cid in criterion_ids if criterion_ids is not None else sorted(counts):
        c_tp, c_fp, c_fn = counts.get(cid, [0, 0, 0])
        per_criterion.append(
            CriterionMetrics(
                criterion_id=cid,
                true_positives=c_tp,
                false_positives=c_fp,
                false_negatives=c_fn,
                precision=_ratio(c_tp, c_tp + c_fp),
                recall=_ratio(c_tp, c_tp + c_fn),
            )
        )
    tp = sum(m.true_positives for m in per_criterion)
    fp = sum(m.false_positives for m in per_criterion)
    fn = sum(m.false_negatives for m in per_criterion)
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)

    return PrecisionReport(
        run_id=str(run.run_id),
        model=run.model,
        conversations_compared=len(comparisons),
        skipped_partial=skipped,
        missing_from_run=sorted(set(ground_truth) - set(audits)),
        not_in_ground_truth=sorted(set(audits) - set(ground_truth)),
        exact_matches=sum(not c.false_positives and not c.false_negatives for c in comparisons),
        severity_matches=sum(c.expected_severity is c.predicted_severity for c in comparisons),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        per_criterion=per_criterion,
        mismatches=[c for c in comparisons if c.false_positives or c.false_negatives],
    )


def render_text(report: PrecisionReport) -> str:
    """Human-readable summary for the terminal and for the documentation."""
    lines = [
        f"Ejecución {report.run_id} | modelo {report.model}",
        f"Conversaciones comparadas: {report.conversations_compared}"
        + (
            f" | omitidas por análisis parcial: {', '.join(report.skipped_partial)}"
            if report.skipped_partial
            else ""
        )
        + (
            f" | ausentes en la ejecución: {', '.join(report.missing_from_run)}"
            if report.missing_from_run
            else ""
        ),
        f"Coincidencia exacta: {report.exact_matches}/{report.conversations_compared} | "
        f"misma severidad: {report.severity_matches}/{report.conversations_compared}",
        f"Fallas: VP={report.true_positives} FP={report.false_positives} "
        f"FN={report.false_negatives} | precisión={report.precision} "
        f"recall={report.recall} F1={report.f1}",
    ]
    failing = [m for m in report.per_criterion if m.false_positives or m.false_negatives]
    if failing:
        lines.append("Criterios con diferencias:")
        lines.extend(
            f"  {m.criterion_id}: VP={m.true_positives} FP={m.false_positives} "
            f"FN={m.false_negatives}"
            for m in failing
        )
    if report.mismatches:
        lines.append("Conversaciones con diferencias:")
        lines.extend(
            f"  {c.conversation_id}: falsos positivos={c.false_positives or '-'} "
            f"falsos negativos={c.false_negatives or '-'}"
            for c in report.mismatches
        )
    return "\n".join(lines)
