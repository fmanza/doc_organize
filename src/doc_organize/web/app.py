"""
FastAPI app factory (REQ-007, Fase D-2a).
"""

from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from doc_organize.core.exceptions import (
    AuthError,
    InvalidPathError,
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectNameError,
    ProjectNotFoundError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    ScannedFolderInUseError,
    ScannedFolderNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from doc_organize.core.models import SecurityConfig
from doc_organize.web.auth import AuthMiddleware, LoginRateLimiter
from doc_organize.web.dependencies import (
    get_auth_store,
    get_project_registry,
    get_scanned_folders_store,
    get_tenant_id,
    require_project_access,
)
from doc_organize.web.pagination import DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, paginate
from doc_organize.web.routes.admin import router as admin_router
from doc_organize.web.routes.auth import router as auth_router
from doc_organize.web.routes.cache import router as cache_router
from doc_organize.web.routes.change_password import router as change_password_router
from doc_organize.web.routes.downloads import router as downloads_router
from doc_organize.web.routes.duplicates import router as duplicates_router
from doc_organize.web.routes.filesystem import router as filesystem_router
from doc_organize.web.routes.projects import router as projects_router
from doc_organize.web.routes.scan import router as scan_router
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"

#: Mapeo por defecto excepción de dominio -> código HTTP, compartido por todas las
#: rutas (Fase de deuda técnica, 2026-08-29): antes cada endpoint repetía su propio
#: `try/except <Error> as exc: raise HTTPException(...)`, ~30 veces en total entre
#: `web/routes/*.py`. Centralizado aquí vía `app.add_exception_handler()` — Starlette
#: resuelve el handler recorriendo el MRO de la excepción, así que una entrada para
#: la clase base (p. ej. `ProjectError` -> 400) actúa de fallback y una entrada más
#: específica (p. ej. `ProjectNotFoundError` -> 404) la sobreescribe correctamente.
#: `RoleNotFoundError` es un caso especial: por defecto es 404 (el rol es el propio
#: recurso de la URL en `/api/roles/{role_id}`), pero `admin.py::create_user`/
#: `update_user` lo capturan localmente y lo remapean a 422 (ahí el rol es una
#: referencia dentro del payload de un usuario, no el recurso direccionado) — ese
#: `try/except` local sigue siendo necesario porque el mismo tipo de excepción
#: significa cosas distintas según el endpoint.
_EXCEPTION_STATUS_CODES: dict[type[Exception], int] = {
    ProjectNotFoundError: 404,
    ProjectAlreadyExistsError: 409,
    ProjectNameError: 422,
    ProjectError: 400,
    RoleNotFoundError: 404,
    RoleAlreadyExistsError: 409,
    RoleInUseError: 409,
    UserNotFoundError: 404,
    UserAlreadyExistsError: 409,
    AuthError: 422,
    InvalidPathError: 422,
    ScannedFolderNotFoundError: 404,
    ScannedFolderInUseError: 409,
}


def _domain_error_handler(status_code: int) -> Callable[[Request, Exception], JSONResponse]:
    def _handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return _handler


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
    # Compartido entre peticiones de /login (revision de seguridad, revision 9): un
    # objeto por app, no por peticion, para que el conteo de fallos sobreviva entre
    # llamadas.
    app.state.login_rate_limiter = LoginRateLimiter()
    app.add_middleware(AuthMiddleware, security=security, auth_db_path=auth_db_path)
    for exc_type, status_code in _EXCEPTION_STATUS_CODES.items():
        app.add_exception_handler(exc_type, _domain_error_handler(status_code))
    app.include_router(auth_router)
    app.include_router(change_password_router)
    app.include_router(admin_router)
    app.include_router(projects_router)
    app.include_router(scan_router)
    app.include_router(filesystem_router)
    app.include_router(cache_router)
    app.include_router(downloads_router)
    app.include_router(duplicates_router)

    templates = create_templates(_TEMPLATES_DIR)

    @app.get("/", response_class=HTMLResponse)
    async def project_selector(
        request: Request,
        q: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> HTMLResponse:
        async with get_project_registry(request) as registry:
            projects = await registry.list_projects(tenant_id=get_tenant_id(request))

        if getattr(request.state, "is_admin", None) is False:
            async with get_auth_store(request) as store:
                role = await store.get_role(get_tenant_id(request), request.state.role_id)
            allowed_names = {allowed.lower() for allowed in role.project_names}
            projects = [project for project in projects if project.name.lower() in allowed_names]

        # Misma funcionalidad que la pestaña Caché de Escanear: buscador server-side
        # (por nombre o ubicación) + paginación, en vez de listar siempre todos los
        # proyectos del tenant/rol de una sola vez.
        q_normalized = (q.strip() or None) if q else None
        if q_normalized:
            needle = q_normalized.lower()
            projects = [project for project in projects if needle in project.name.lower() or needle in project.root_path.lower()]

        resolved_page = paginate(len(projects), page, page_size)
        offset = (resolved_page.number - 1) * resolved_page.size
        page_projects = projects[offset : offset + resolved_page.size]

        return templates.TemplateResponse(
            request,
            "project_selector.html.j2",
            {
                "projects": page_projects,
                "q": q_normalized,
                "page": resolved_page.number,
                "page_size": resolved_page.size,
                "page_size_options": PAGE_SIZE_OPTIONS,
                "total": resolved_page.total,
                "total_pages": resolved_page.total_pages,
                "range_start": resolved_page.range_start,
                "range_end": resolved_page.range_end,
            },
        )

    @app.get("/projects/{name}", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
    async def dashboard(name: str, request: Request) -> HTMLResponse:
        # ProjectNotFoundError se propaga sin capturar: el handler global
        # registrado arriba (_EXCEPTION_STATUS_CODES) la traduce a 404.
        async with get_project_registry(request) as registry:
            project = await registry.get_project(name, tenant_id=get_tenant_id(request))
        folders = await get_scanned_folders_store().list_folders(project)
        return templates.TemplateResponse(request, "dashboard.html.j2", {"project": project, "folders": folders})

    return app


__all__ = ["create_app"]
