"""HTTP routes. Thin: parse, delegate to the application service, return domain models."""

import asyncio
import json
from typing import Annotated, Any, Literal
from uuid import UUID

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
from callaudit.application.audit_service import AuditService
from callaudit.application.models import DatasetAudit
from callaudit.application.ports import PersistenceError, PersistenceUnavailableError
from callaudit.domain.audit import ConversationAudit, Severity
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.criteria import RUBRIC, RUBRIC_VERSION

# Guard rails for a free-tier deployment: one dataset run is bounded in size.
MAX_CONVERSATIONS_PER_RUN = 100
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

SCORING_RULE = (
    "Puntaje = 100 * suma(pesos de criterios que cumplen) / suma(pesos de criterios aplicables). "
    "'no_aplica' e 'indeterminado' no cuentan. La severidad de la conversación es la mayor "
    "severidad entre sus criterios incumplidos."
)

HEALTH_DB_TIMEOUT_SECONDS = 3

_INVALID_FORMAT = "El archivo no tiene el formato esperado."

_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
}

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
}


class UploadedFileError(Exception):
    """An uploaded file that is not valid JSON or does not have the expected shape."""

    def __init__(self, message: str, details: list[tuple[str, str]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []

    @classmethod
    def from_validation(cls, message: str, error: ValidationError) -> "UploadedFileError":
        return cls(
            message,
            [(".".join(str(part) for part in e["loc"]), e["msg"]) for e in error.errors()],
        )


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
    """Liveness: always 200 while the process is up. The database state is informative."""
    repository = service.repository
    database: Literal["ok", "error", "no_configurada"] = "no_configurada"
    if repository.enabled:
        try:
            await asyncio.wait_for(repository.ping(), timeout=HEALTH_DB_TIMEOUT_SECONDS)
            database = "ok"
        except Exception:
            database = "error"
    return HealthResponse(
        status="ok",
        language_model=service.model_name,
        rubric_version=RUBRIC_VERSION,
        persistence=repository.name,
        database=database,
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
    return await service.audit_conversation(payload.conversation, payload.agent_spec)


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
    summary="Auditar varias conversaciones (JSON en el cuerpo)",
    description="Recibe `{conversaciones: [ ... ]}` y devuelve la auditoría de cada "
    "conversación más el reporte agregado. `especificacion_agente` y `descripcion` son "
    "opcionales, de modo que también se acepta el archivo del cliente tal como se entrega.",
    responses=_ERRORS,
)
async def audit_dataset(
    service: Service,
    dataset: Annotated[Dataset, Body(openapi_examples=DATASET_REQUEST_EXAMPLES)],
) -> DatasetAudit:
    _check_size(dataset)
    return await service.audit_dataset(dataset)


async def _read_upload(file: UploadFile) -> Any:
    """Read an uploaded JSON file with a size cap, without loading more than the limit."""
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"El archivo supera el máximo de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UploadedFileError("El archivo no es un JSON válido.", [("file", str(exc))]) from exc


@router.post(
    "/v1/audits/file",
    tags=["auditorías"],
    summary="Auditar una conversación (subida de archivo)",
    description="Recibe un archivo .json con una sola conversación, en cualquiera de dos formas: "
    "la conversación sola (`{id, fecha_llamada, datos_cliente, transcripcion}`) o la misma "
    "estructura del lote con una única conversación (`{conversaciones: [ ... ]}`). "
    "La especificación del agente es opcional; si no viene, se usa la de Lina.",
    responses=_ERRORS,
)
async def audit_one_file(
    service: Service,
    file: Annotated[UploadFile, File(description="Archivo JSON con una conversación.")],
) -> ConversationAudit:
    data = await _read_upload(file)
    if isinstance(data, dict) and "conversaciones" in data:
        try:
            dataset = Dataset.model_validate(data)
        except ValidationError as exc:
            raise UploadedFileError.from_validation(_INVALID_FORMAT, exc) from exc
        if len(dataset.conversations) != 1:
            raise UploadedFileError(
                f"El archivo trae {len(dataset.conversations)} conversaciones; esta ruta audita "
                "una sola. Para varias, use POST /v1/audits/dataset/file."
            )
        return await service.audit_conversation(dataset.conversations[0], dataset.agent_spec)
    try:
        conversation = Conversation.model_validate(data)
    except ValidationError as exc:
        raise UploadedFileError.from_validation(_INVALID_FORMAT, exc) from exc
    return await service.audit_conversation(conversation)


@router.post(
    "/v1/audits/dataset/file",
    tags=["auditorías"],
    summary="Auditar varias conversaciones (subida de archivo)",
    description="Igual que /v1/audits/dataset, pero recibe el archivo .json como subida "
    "multipart: `{conversaciones: [ ... ]}`, o el archivo del cliente tal como se entrega "
    "(con `descripcion` y `especificacion_agente`). Pensado para usarlo desde esta página.",
    responses=_ERRORS,
)
async def audit_dataset_file(
    service: Service,
    file: Annotated[UploadFile, File(description="Archivo JSON con las conversaciones.")],
) -> DatasetAudit:
    data = await _read_upload(file)
    try:
        dataset = Dataset.model_validate(data)
    except ValidationError as exc:
        raise UploadedFileError.from_validation(_INVALID_FORMAT, exc) from exc
    _check_size(dataset)
    return await service.audit_dataset(dataset)


def _unavailable(exc: PersistenceError) -> HTTPException:
    reason = (
        "La persistencia no está configurada en este despliegue."
        if isinstance(exc, PersistenceUnavailableError)
        else "La base de datos no respondió; intente más tarde."
    )
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=reason)


@router.get(
    "/v1/audits/{audit_id}",
    tags=["consultas"],
    summary="Recuperar una auditoría guardada",
    responses=_READ_ERRORS,
)
async def get_audit(service: Service, audit_id: UUID) -> ConversationAudit:
    try:
        audit = await service.get_audit(audit_id)
    except PersistenceError as exc:
        raise _unavailable(exc) from exc
    if audit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe la auditoría {audit_id}.")
    return audit


@router.get(
    "/v1/reports/{run_id}",
    tags=["consultas"],
    summary="Recuperar el reporte de una ejecución sobre un dataset",
    description="Devuelve la ejecución completa: el reporte agregado y todas sus auditorías.",
    responses=_READ_ERRORS,
)
async def get_report(service: Service, run_id: UUID) -> DatasetAudit:
    try:
        run = await service.get_run(run_id)
    except PersistenceError as exc:
        raise _unavailable(exc) from exc
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe la ejecución {run_id}.")
    return run
