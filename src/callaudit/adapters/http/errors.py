"""One error shape for every failure: {"error": {"code", "message", "details"}}."""

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from callaudit.adapters.http.routes import DatasetFileError
from callaudit.adapters.http.schemas import ErrorBody, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

_CODES = {
    status.HTTP_404_NOT_FOUND: "no_encontrado",
    status.HTTP_405_METHOD_NOT_ALLOWED: "metodo_no_permitido",
    status.HTTP_413_CONTENT_TOO_LARGE: "demasiado_grande",
}


def _response(
    status_code: int, code: str, message: str, details: list[ErrorDetail]
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _details(errors: Iterable[Mapping[str, Any]]) -> list[ErrorDetail]:
    return [
        ErrorDetail(
            location=".".join(str(part) for part in error.get("loc", ())),
            message=str(error.get("msg", "")),
        )
        for error in errors
    ]


async def _validation(_: Request, exc: Exception) -> JSONResponse:
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "entrada_invalida",
        "La solicitud no cumple el formato esperado.",
        _details(errors),
    )


async def _dataset_file(_: Request, exc: Exception) -> JSONResponse:
    errors = exc.error.errors() if isinstance(exc, DatasetFileError) else []
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "archivo_invalido",
        "El archivo no es un JSON válido con el formato del dataset.",
        _details(errors),
    )


async def _http(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return await _unexpected(_, exc)
    return _response(
        exc.status_code,
        _CODES.get(exc.status_code, "error_http"),
        str(exc.detail),
        [],
    )


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals to the client; the full traceback goes to the log.
    logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return _response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "error_interno",
        "Ocurrió un error inesperado. El detalle quedó registrado en el servidor.",
        [],
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(DatasetFileError, _dataset_file)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _unexpected)
