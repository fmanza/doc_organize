"""
Folder Selector + escaneo/conversión vía web con progreso WebSocket (Fase D-2b, §2.7.3).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.scan import ScanCommand
from doc_organize.utils.logging import get_logger
from doc_organize.validators import FolderValidator
from doc_organize.web.auth import authenticate_session, requires_auth
from doc_organize.web.dependencies import get_project_registry, get_tenant_id

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


@router.get("/projects/{name}/scan", response_class=HTMLResponse)
async def folder_selector(name: str, request: Request) -> HTMLResponse:
    try:
        async with get_project_registry(request) as registry:
            project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _templates.TemplateResponse(request, "folder_selector.html", {"project": project})


@router.post("/api/projects/{name}/folders/validate", response_model=ValidateFoldersResponse)
async def validate_folders(name: str, payload: ValidateFoldersRequest, request: Request) -> ValidateFoldersResponse:
    # Confirma que el proyecto existe y pertenece al tenant de la sesion, aunque esta
    # ruta en si no lo toca -- evita usar este endpoint para sondear nombres de
    # proyecto de otro tenant sin pasar por ningun chequeo de pertenencia.
    async with get_project_registry(request) as registry:
        try:
            await registry.get_project(name, tenant_id=get_tenant_id(request))
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = FolderValidator().validate_folder_set(payload.paths)
    return ValidateFoldersResponse(valid=result.is_valid, warnings=result.warnings, clean_paths=result.clean_paths)


@router.websocket("/api/projects/{name}/scan")
async def scan_websocket(name: str, websocket: WebSocket) -> None:
    """Escanea/convierte el proyecto `name`, retransmitiendo cada `ScanEvent` como JSON.

    Autenticación manual (Fase D-2b, §2.7.3): `AuthMiddleware` extiende
    `BaseHTTPMiddleware`, que **no** intercepta conexiones WebSocket — Starlette pasa
    el scope `"websocket"` directo a la app interna sin llamar a `dispatch()`. Sin
    esta comprobación explícita, esta ruta quedaría accesible sin sesión aunque el
    resto de la app la exija en modo no-loopback.
    """
    await websocket.accept()

    security = websocket.app.state.security
    auth_db_path = getattr(websocket.app.state, "auth_db_path", None)

    if requires_auth(security):
        session = await authenticate_session(websocket.cookies, auth_db_path)
        if session is None:
            await websocket.close(code=1008, reason="Unauthorized")
            return
        tenant_id = session.tenant_id
    else:
        tenant_id = "default"

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
