"""HTTP routes. Thin: parse, delegate to the application service, return domain models."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from callaudit.adapters.http.examples import (
    CONVERSATION_REQUEST_EXAMPLES,
    DATASET_REQUEST_EXAMPLES,
)
from callaudit.adapters.http.schemas import (
    ConversationAuditRequest,
    CriterionInfo,
    ErrorResponse,
    HealthResponse,
    RubricResponse,
)
from callaudit.application.agent_spec import LINA_AGENT_SPEC
from callaudit.application.audit_service import AuditService
from callaudit.application.models import DatasetAudit
from callaudit.domain.audit import ConversationAudit, Severity
from callaudit.domain.conversation import Dataset
from callaudit.domain.criteria import RUBRIC, RUBRIC_VERSION

# Guard rails for a free-tier deployment: one dataset run is bounded in size.
MAX_CONVERSATIONS_PER_RUN = 100
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

SCORING_RULE = (
    "Puntaje = 100 * suma(pesos de criterios que cumplen) / suma(pesos de criterios aplicables). "
    "'no_aplica' e 'indeterminado' no cuentan. La severidad de la conversación es la mayor "
    "severidad entre sus criterios incumplidos."
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
}


class DatasetFileError(Exception):
    """An uploaded file that is not valid JSON or does not match the dataset format."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__(str(error))
        self.error = error


def get_audit_service(request: Request) -> AuditService:
    service: AuditService = request.app.state.audit_service
    return service


Service = Annotated[AuditService, Depends(get_audit_service)]

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@router.get("/health", tags=["operación"], summary="Estado del servicio")
async def health(service: Service) -> HealthResponse:
    return HealthResponse(
        status="ok",
        language_model=service.model_name,
        rubric_version=RUBRIC_VERSION,
    )


@router.get("/v1/rubric", tags=["rúbrica"], summary="Criterios, pesos y regla de puntaje")
async def rubric() -> RubricResponse:
    return RubricResponse(
        version=RUBRIC_VERSION,
        scoring=SCORING_RULE,
        severity_weights={s: s.weight for s in Severity if s is not Severity.NONE},
        criteria=[
            CriterionInfo(
                criterion_id=c.id,
                rule_id=c.rule_id,
                title=c.title,
                severity=c.severity,
                weight=c.severity.weight,
                method=c.method,
                requires_language_model=c.requires_facts,
            )
            for c in RUBRIC
        ],
    )


@router.post(
    "/v1/audits",
    tags=["auditorías"],
    summary="Auditar una conversación",
    responses=_ERRORS,
)
async def audit_one(
    service: Service,
    payload: Annotated[
        ConversationAuditRequest, Body(openapi_examples=CONVERSATION_REQUEST_EXAMPLES)
    ],
) -> ConversationAudit:
    return await service.audit_conversation(
        payload.conversation, payload.agent_spec or LINA_AGENT_SPEC
    )


def _check_size(dataset: Dataset) -> None:
    if len(dataset.conversations) > MAX_CONVERSATIONS_PER_RUN:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Máximo {MAX_CONVERSATIONS_PER_RUN} conversaciones por ejecución; "
            f"se recibieron {len(dataset.conversations)}.",
        )


@router.post(
    "/v1/audits/dataset",
    tags=["auditorías"],
    summary="Auditar un dataset completo (JSON en el cuerpo)",
    description="Recibe el archivo con el mismo formato que entrega el cliente y devuelve la "
    "auditoría de cada conversación más el reporte agregado.",
    responses=_ERRORS,
)
async def audit_dataset(
    service: Service,
    dataset: Annotated[Dataset, Body(openapi_examples=DATASET_REQUEST_EXAMPLES)],
) -> DatasetAudit:
    _check_size(dataset)
    return await service.audit_dataset(dataset)


@router.post(
    "/v1/audits/dataset/file",
    tags=["auditorías"],
    summary="Auditar un dataset completo (subida de archivo)",
    description="Igual que /v1/audits/dataset, pero recibe el archivo .json como subida "
    "multipart. Pensado para usarlo directamente desde esta página.",
    responses=_ERRORS,
)
async def audit_dataset_file(
    service: Service,
    file: Annotated[UploadFile, File(description="Archivo JSON del dataset.")],
) -> DatasetAudit:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"El archivo supera el máximo de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    try:
        dataset = Dataset.model_validate_json(raw)
    except ValidationError as exc:
        # Re-raised as the same 422 shape a JSON body would produce.
        raise DatasetFileError(exc) from exc
    _check_size(dataset)
    return await service.audit_dataset(dataset)
