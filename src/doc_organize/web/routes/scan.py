"""
Folder Selector + escaneo/conversión vía web con progreso WebSocket (Fase D-2b, §2.7.3).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.scan import ScanCommand
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import is_subpath
from doc_organize.validators import FolderValidator
from doc_organize.web.auth import authenticate_session, requires_auth
from doc_organize.web.dependencies import get_auth_store, get_project_registry, get_tenant_id, require_project_access

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(tags=["scan"])


class ValidateFoldersRequest(BaseModel):
    paths: list[str]


class ValidateFoldersResponse(BaseModel):
    valid: bool
    warnings: list[str]
    clean_paths: list[str]


@router.get("/projects/{name}/scan", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def folder_selector(name: str, request: Request) -> HTMLResponse:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    return _templates.TemplateResponse(request, "folder_selector.html.j2", {"project": project})


@router.post(
    "/api/projects/{name}/folders/validate",
    response_model=ValidateFoldersResponse,
    dependencies=[Depends(require_project_access)],
)
async def validate_folders(name: str, payload: ValidateFoldersRequest, request: Request) -> ValidateFoldersResponse:
    # Confirma que el proyecto existe y pertenece al tenant de la sesion, aunque esta
    # ruta en si no lo toca -- evita usar este endpoint para sondear nombres de
    # proyecto de otro tenant sin pasar por ningun chequeo de pertenencia.
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        await registry.get_project(name, tenant_id=get_tenant_id(request))

    result = FolderValidator().validate_folder_set(payload.paths)
    return ValidateFoldersResponse(valid=result.is_valid, warnings=result.warnings, clean_paths=result.clean_paths)


def _paths_within_roots(paths: list[str], allowed_roots: list[str]) -> bool:
    """`True` si cada ruta de `paths` es (o está dentro de) alguna de `allowed_roots`.

    Sin `allowed_roots` configuradas, un rol restringido no puede escanear ninguna
    ruta externa: antes de esta comprobación, cualquier rol con acceso a un
    proyecto podía indicar cualquier ruta legible por el proceso servidor,
    evadiendo por completo la restricción de `project_names` (revisión de
    seguridad, revisión 9 roles y gestión de usuarios).
    """
    if not paths:
        return True
    if not allowed_roots:
        return False
    return all(any(is_subpath(path, root) for root in allowed_roots) for path in paths)


async def _authorize_scan_websocket(websocket: WebSocket, project_name: str) -> tuple[str, list[str] | None] | None:
    """Autentica (si aplica) y resuelve `tenant_id` + `allowed_scan_roots` para la conexión.

    Autenticación manual (Fase D-2b, §2.7.3): `AuthMiddleware` extiende
    `BaseHTTPMiddleware`, que **no** intercepta conexiones WebSocket — Starlette pasa
    el scope `"websocket"` directo a la app interna sin llamar a `dispatch()`. Sin
    esta comprobación explícita, esta ruta quedaría accesible sin sesión aunque el
    resto de la app la exija en modo no-loopback.

    Devuelve `None` si ya se cerró el websocket (sin sesión válida, o sin acceso al
    proyecto) — el llamador no debe hacer nada más. `allowed_scan_roots` es `None`
    cuando no hay restricción de rutas (admin o loopback/sin auth); una lista
    (posiblemente vacía) restringe los `paths` aceptados a esas raíces.
    """
    security = websocket.app.state.security
    auth_db_path = getattr(websocket.app.state, "auth_db_path", None)

    if not requires_auth(security):
        return "default", None

    authenticated = await authenticate_session(websocket.cookies, auth_db_path)
    if authenticated is None:
        await websocket.close(code=1008, reason="Unauthorized")
        return None

    tenant_id = authenticated.session.tenant_id
    if authenticated.is_admin:
        return tenant_id, None

    async with get_auth_store(websocket) as store:
        allowed = await store.can_access_project(tenant_id, authenticated.role_id, project_name)
        if not allowed:
            await websocket.close(code=1008, reason="Project not found")
            return None
        role = await store.get_role(tenant_id, authenticated.role_id)
        return tenant_id, role.allowed_scan_roots


@router.websocket("/api/projects/{name}/scan")
async def scan_websocket(name: str, websocket: WebSocket) -> None:
    """Escanea/convierte el proyecto `name`, retransmitiendo cada `ScanEvent` como JSON."""
    await websocket.accept()

    auth_result = await _authorize_scan_websocket(websocket, name)
    if auth_result is None:
        return
    tenant_id, allowed_scan_roots = auth_result

    async with get_project_registry(websocket) as registry:
        try:
            project = await registry.get_project(name, tenant_id=tenant_id)
        except ProjectNotFoundError:
            await websocket.close(code=1008, reason="Project not found")
            return

    try:
        request_payload = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    paths = [str(p) for p in request_payload.get("paths", [])]
    if allowed_scan_roots is not None and not _paths_within_roots(paths, allowed_scan_roots):
        await websocket.close(code=1008, reason="Forbidden path")
        return

    deduplicate = bool(request_payload.get("deduplicate", False))
    use_ocr = bool(request_payload.get("use_ocr", False))
    use_gpu = bool(request_payload.get("use_gpu", False))

    root = Path(project.root_path)
    try:
        async for event in ScanCommand().run_streaming(
            paths=paths,
            output_dir=root / "Conversión",
            cache_db=root / "cache.db",
            duplicates_dir=root / "duplicados",
            folders_json=root / "folders.json",
            deduplicate=deduplicate,
            use_ocr=use_ocr,
            use_gpu=use_gpu,
        ):
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.info(f"Cliente desconectado durante el escaneo de '{name}' (tenant '{tenant_id}')")
        return

    await websocket.close()


__all__ = ["router"]
