"""Documentation pages and the site icon.

FastAPI's default /docs and /redoc load FastAPI's own favicon from its
website. These routes render the same pages with the service's icon, which
ships inside the package so it is part of the Docker image.
"""

from importlib.resources import files

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse, Response

FAVICON_PATH = "/favicon.svg"
_FAVICON = files("callaudit.adapters.http").joinpath("static/favicon.svg").read_bytes()

router = APIRouter(include_in_schema=False)


@router.get(FAVICON_PATH)
async def favicon() -> Response:
    return Response(
        _FAVICON,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/favicon.ico")
async def favicon_ico() -> RedirectResponse:
    # Browsers request /favicon.ico on their own; point them to the SVG.
    return RedirectResponse(FAVICON_PATH, status_code=301)


@router.get("/docs")
async def swagger_ui(request: Request) -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=request.app.openapi_url,
        title=f"{request.app.title} - Swagger",
        swagger_favicon_url=FAVICON_PATH,
    )


@router.get("/redoc")
async def redoc(request: Request) -> HTMLResponse:
    return get_redoc_html(
        openapi_url=request.app.openapi_url,
        title=f"{request.app.title} - ReDoc",
        redoc_favicon_url=FAVICON_PATH,
    )
