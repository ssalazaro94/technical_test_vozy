"""Output of a dataset run: the report plus every conversation audit."""

from collections import Counter
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

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

    @computed_field(  # type: ignore[prop-decorator]
        description="Cuántas auditorías obtuvieron sus hechos del modelo, del caché o del "
        "replay; las parciales cuentan como 'sin_analisis'."
    )
    @property
    def facts_origin_distribution(self) -> dict[str, int]:
        counts = Counter(
            audit.facts_origin.value if audit.facts_origin else "sin_analisis"
            for audit in self.audits
        )
        return dict(sorted(counts.items()))
