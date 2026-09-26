"""Output of a dataset run: the report plus every conversation audit."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from callaudit.domain.audit import ConversationAudit
from callaudit.domain.report import DatasetReport


class DatasetAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    generated_at: datetime
    rubric_version: str
    model: str = Field(description="Modelo de lenguaje usado para extraer los hechos.")
    report: DatasetReport
    audits: list[ConversationAudit]
    persisted: bool = Field(
        default=False,
        description="Si la ejecución quedó guardada y puede recuperarse por run_id.",
    )
