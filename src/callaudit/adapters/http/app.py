"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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

Para evaluar el archivo del cliente desde esta página, use **POST /v1/audits/dataset/file**.
Las auditorías y ejecuciones quedan guardadas y se consultan con **GET /v1/audits/{audit_id}**
y **GET /v1/reports/{run_id}**.
"""


def create_app(service: AuditService | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests inject a service; production builds it from the environment."""
    if service is None:
        service = build_audit_service(settings or Settings())
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
    )
    app.state.audit_service = service
    app.include_router(router)
    register_error_handlers(app)
    return app
