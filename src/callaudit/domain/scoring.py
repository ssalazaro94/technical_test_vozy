"""Weighted score and overall severity of an audited conversation."""

from collections.abc import Sequence

from callaudit.domain.audit import CriterionResult, Severity, Status


def weighted_score(results: Sequence[CriterionResult]) -> float:
    """Share of applicable severity weight that was met, on a 0-100 scale.

    "no_aplica" and "indeterminado" leave both numerator and denominator, so a
    call is neither rewarded nor punished for rules that did not come up.
    """
    judged = [r for r in results if r.status in {Status.COMPLIES, Status.VIOLATES}]
    total = sum(r.severity.weight for r in judged)
    if total == 0:
        return 100.0
    met = sum(r.severity.weight for r in judged if r.status is Status.COMPLIES)
    return round(100 * met / total, 1)


def overall_severity(results: Sequence[CriterionResult]) -> Severity:
    failed = [r.severity for r in results if r.status is Status.VIOLATES]
    return max(failed, key=lambda severity: severity.weight, default=Severity.NONE)
