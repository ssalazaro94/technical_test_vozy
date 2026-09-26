"""The rubric: every criterion, in rule order.

Adding a criterion means writing one pure function and one `Criterion` entry in
its module; the engine, the score and the report pick it up from here.
"""

from callaudit.domain.criteria import conduct, disclosure, handling, identity, negotiation
from callaudit.domain.criteria.base import AuditContext, Criterion, Finding

RUBRIC_VERSION = "2026-09-25"

RUBRIC: tuple[Criterion, ...] = (
    *identity.CRITERIA,
    *disclosure.CRITERIA,
    *negotiation.CRITERIA,
    *handling.CRITERIA,
    *conduct.CRITERIA,
)

__all__ = ["RUBRIC", "RUBRIC_VERSION", "AuditContext", "Criterion", "Finding"]
