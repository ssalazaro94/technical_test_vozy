"""Output model: the audit of one conversation.

The shape is identical for every conversation, including degraded ones, so a
consumer never has to branch on missing keys.
"""

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from callaudit.domain.conversation import Speaker
from callaudit.domain.facts import Outcome


class Status(StrEnum):
    COMPLIES = "cumple"
    VIOLATES = "no_cumple"
    NOT_APPLICABLE = "no_aplica"
    # Only used when the language model analysis failed and the criterion
    # depends on it. It is excluded from the score and reported separately.
    UNDETERMINED = "indeterminado"


class Severity(StrEnum):
    NONE = "ninguna"
    MINOR = "leve"
    MAJOR = "grave"
    CRITICAL = "critica"

    @property
    def weight(self) -> int:
        return _SEVERITY_WEIGHTS[self]


_SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.NONE: 0,
    Severity.MINOR: 1,
    Severity.MAJOR: 3,
    Severity.CRITICAL: 5,
}


class Method(StrEnum):
    CODE = "codigo"
    LLM = "llm"
    HYBRID = "hibrido"


class AnalysisStatus(StrEnum):
    COMPLETE = "completo"
    PARTIAL = "parcial"


class _OutputModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Evidence(_OutputModel):
    turn: int = Field(ge=0, description="Índice del turno en la transcripción (base 0).")
    speaker: Speaker
    quote: str = Field(description="Texto literal del turno, copiado de la transcripción.")


class CriterionResult(_OutputModel):
    criterion_id: str
    rule_id: str
    title: str
    method: Method
    severity: Severity = Field(description="Severidad asignada al criterio si no se cumple.")
    status: Status
    evidence: list[Evidence]
    explanation: str

    @model_validator(mode="after")
    def _violation_requires_evidence(self) -> Self:
        if self.status is Status.VIOLATES and not self.evidence:
            raise ValueError(f"{self.criterion_id}: un 'no_cumple' requiere al menos una cita")
        return self


class ConversationAudit(_OutputModel):
    conversation_id: str
    call_date: date
    analysis: AnalysisStatus
    outcome: Outcome | None = Field(
        description="Resultado de la gestión; nulo si el análisis del modelo falló.",
    )
    score: float = Field(ge=0, le=100, description="Cumplimiento ponderado por severidad (0-100).")
    severity: Severity = Field(description="Severidad máxima entre los criterios incumplidos.")
    failed_criteria: list[str]
    criteria: list[CriterionResult]
    warnings: list[str]
