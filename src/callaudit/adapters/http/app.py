"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from callaudit.adapters.http.client_limits import ClientRateLimiter
from callaudit.adapters.http.docs import router as docs_router
from callaudit.adapters.http.errors import register_error_handlers
from callaudit.adapters.http.routes import router
from callaudit.application.audit_service import AuditService
from callaudit.bootstrap import build_audit_service
from callaudit.config import Settings

DESCRIPTION = """\
Audita llamadas de cobranza del agente de voz **Lina** (Banco Andino) contra una rúbrica
de 21 criterios derivada de sus 10 reglas de negocio.

- Cada criterio devuelve `cumple`, `no_cumple` o `no_aplica`, con la cita textual del turno
  que lo justifica y una explicación. Si el modelo de lenguaje no está disponible, los
  criterios que dependen de él quedan `indeterminado` y la auditoría se marca `parcial`.
- Cada conversación recibe un puntaje de 0 a 100 ponderado por severidad y una severidad
  global (`ninguna`, `leve`, `grave`, `critica`).
- La auditoría de un dataset incluye además un reporte agregado: tasa de cumplimiento por
  criterio y fallas más frecuentes.

Para subir archivos desde esta página: **POST /v1/audits/file** (una conversación) y
**POST /v1/audits/dataset/file** (varias, `{conversaciones: [...]}`, o el archivo del cliente
tal como se entrega). La especificación del agente es opcional en todas las rutas.
Las auditorías y ejecuciones quedan guardadas y se consultan con **GET /v1/audits/{audit_id}**
y **GET /v1/reports/{run_id}**.
"""


def create_app(
    service: AuditService | None = None,
    settings: Settings | None = None,
    client_limiter: ClientRateLimiter | None = None,
) -> FastAPI:
    """Build the app. Tests inject a service; production builds it from the environment.

    The per-client limit comes from the settings when the app builds its own
    service; an injected service gets only the limiter passed explicitly.
    """
    if service is None:
        settings = settings or Settings()
        service = build_audit_service(settings)
        if client_limiter is None and settings.client_requests_per_hour is not None:
            client_limiter = ClientRateLimiter(settings.client_requests_per_hour)
    audit_service = service

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Release database connections on shutdown (Render sends SIGTERM on deploys).
        await audit_service.repository.close()

    app = FastAPI(
        title="Auditoría de llamadas de cobranza",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        # Rendered by adapters.http.docs, with the service's own favicon.
        docs_url=None,
        redoc_url=None,
    )
    app.state.audit_service = service
    app.state.client_limiter = client_limiter
    app.include_router(docs_router)
    app.include_router(router)
    register_error_handlers(app)
    return app
