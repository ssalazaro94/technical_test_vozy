"""HTTP-only request and response models. Domain models are reused as-is."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from callaudit.domain.audit import Method, Severity
from callaudit.domain.conversation import AgentSpec, Conversation


class ConversationAuditRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversation: Conversation = Field(alias="conversacion")
    agent_spec: AgentSpec | None = Field(
        default=None,
        alias="especificacion_agente",
        description="Si se omite, se usa la especificación de Lina (Banco Andino).",
    )


class CriterionInfo(BaseModel):
    criterion_id: str
    rule_id: str
    title: str
    severity: Severity
    weight: int
    method: Method
    requires_language_model: bool


class RubricResponse(BaseModel):
    version: str
    scoring: str
    severity_weights: dict[Severity, int]
    criteria: list[CriterionInfo]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    language_model: str
    rubric_version: str


class ErrorDetail(BaseModel):
    location: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
