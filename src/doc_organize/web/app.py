"""
FastAPI app factory (REQ-007, Fase D-2a).
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.core.models import SecurityConfig
from doc_organize.web.auth import AuthMiddleware
from doc_organize.web.dependencies import get_project_registry, get_tenant_id
from doc_organize.web.routes.auth import router as auth_router
from doc_organize.web.routes.cache import router as cache_router
from doc_organize.web.routes.downloads import router as downloads_router
from doc_organize.web.routes.duplicates import router as duplicates_router
from doc_organize.web.routes.projects import router as projects_router
from doc_organize.web.routes.scan import router as scan_router

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(
    security: SecurityConfig | None = None,
    registry_path: str | Path | None = None,
    auth_db_path: str | Path | None = None,
) -> FastAPI:
    """Crea la app FastAPI de doc_organize (REQ-007, Fase D-2a + revisión 8 §2.7.2).

    Args:
        security: Configuración de host/puerto. Por defecto, loopback sin auth.
        registry_path: Ruta alternativa al registro de proyectos (uso en tests, para
            no tocar `~/.doc_organize/projects.json`).
        auth_db_path: Ruta alternativa a la base de datos de autenticación (uso en
            tests, para no tocar `~/.doc_organize/auth.db`). Ya no existe un
            parámetro `api_token`: la revisión 8 retira el bearer compartido en
            favor de sesión por usuario (`§2.7.2`).

    Returns:
        La app FastAPI, con la autenticación (`AuthMiddleware`), las rutas de
        login/logout y las rutas de proyectos ya montadas.
    """
    security = security or SecurityConfig()
    app = FastAPI(title="doc_organize")
    app.state.registry_path = str(registry_path) if registry_path else None
    app.state.auth_db_path = str(auth_db_path) if auth_db_path else None
    # Expuesto en app.state (no solo pasado al middleware): el handler WebSocket de
    # web/routes/scan.py necesita `security` para autenticar a mano (Fase D-2b,
    # §2.7.3 — BaseHTTPMiddleware no protege rutas WebSocket).
    app.state.security = security
    app.add_middleware(AuthMiddleware, security=security, auth_db_path=auth_db_path)
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(scan_router)
    app.include_router(cache_router)
    app.include_router(downloads_router)
    app.include_router(duplicates_router)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    async def project_selector(request: Request) -> HTMLResponse:
        async with get_project_registry(request) as registry:
            projects = await registry.list_projects(tenant_id=get_tenant_id(request))
        return templates.TemplateResponse(request, "project_selector.html", {"projects": projects})

    @app.get("/projects/{name}", response_class=HTMLResponse)
    async def dashboard(name: str, request: Request) -> HTMLResponse:
        try:
            async with get_project_registry(request) as registry:
                project = await registry.get_project(name, tenant_id=get_tenant_id(request))
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(request, "dashboard.html", {"project": project})

    return app


__all__ = ["create_app"]
