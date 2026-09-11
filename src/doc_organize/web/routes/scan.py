"""
Folder Selector + escaneo/conversión vía web con progreso WebSocket (Fase D-2b, §2.7.3).

Incluye también la pestaña "Caché" de la página Escanear (antigua página Caché
independiente, Fase D-2c §2.7.4, fusionada aquí en la reestructuración de navegación).
"""

import asyncio
import json

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from doc_organize.cache import CacheManager
from doc_organize.core.constants import (
    AV_SUPPORTED_EXTENSIONS,
    CONVERSION_FOLDER_NAME,
    DEFAULT_CACHE_DB_NAME,
    DUPLICATES_FOLDER_NAME,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_ERRORS_HISTORY_JSONL_NAME,
    SCAN_FOLDERS_JSON_NAME,
    SCAN_HISTORY_FOLDER_NAME,
    SCAN_HISTORY_JSONL_NAME,
    SUPPORTED_EXTENSIONS,
)
from doc_organize.core.models import Project, ScanEventType, ScannedFolder, ScanRunReport
from doc_organize.scan import ScanCommand, list_scan_runs
from doc_organize.utils.av_detector import detect_av_status
from doc_organize.utils.gpu_detector import detect_gpu_status
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import paths_within_roots
from doc_organize.validators import FolderValidator
from doc_organize.web.dependencies import (
    acquire_project_operation_lock,
    authorize_project_websocket,
    get_allowed_scan_roots,
    get_project_registry,
    get_scanned_folders_store,
    get_tenant_id,
    release_project_operation_lock,
    require_project_access,
    resolve_ws_project,
)
from doc_organize.web.pagination import DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, Page, paginate
from doc_organize.web.routes.cache import CacheEntryResponse, cache_entry_to_response
from doc_organize.web.templating import create_templates

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)


def _dirname(full_path: str) -> str:
    """Carpeta contenedora de `full_path`, para la pestaña Caché de Escanear (mismo
    criterio que en Duplicates Resolver)."""
    return str(Path(full_path).parent)


def _basename(full_path: str) -> str:
    """Nombre de archivo de `full_path`, sin la carpeta contenedora, para la columna
    "Archivo" de la pestaña Caché."""
    return Path(full_path).name


_templates.env.filters["dirname"] = _dirname
_templates.env.filters["basename"] = _basename

router = APIRouter(tags=["scan"])


def _scan_history_path(project: Project) -> Path:
    """Ruta a `historial_escaneo/SCAN_HISTORY.jsonl` de `project` (histórico de
    duración de ejecuciones, ver `scan.scan_history_store`)."""
    return Path(project.root_path) / SCAN_HISTORY_FOLDER_NAME / SCAN_HISTORY_JSONL_NAME


async def _load_scan_history(project: Project) -> list[ScanRunReport]:
    """Histórico de ejecuciones de escaneo de `project`, más reciente primero
    (usado tanto para la pestaña "Historial" como para "Última ejecución")."""
    return await asyncio.to_thread(list_scan_runs, _scan_history_path(project))


async def _load_cache_page(project: Project, *, q: str | None, page: int, page_size: int) -> tuple[list[CacheEntryResponse], Page]:
    """Carga una página de `cache_entries` para la pestaña Caché de Escanear."""
    cache_db = Path(project.root_path) / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        total = await cache.count_entries(q)
        resolved_page = paginate(total, page, page_size)
        offset = (resolved_page.number - 1) * resolved_page.size
        page_entries = await cache.load_cache_page(resolved_page.size, offset, q)

    entries = [cache_entry_to_response(entry) for entry in page_entries]
    return entries, resolved_page


class ValidateFoldersRequest(BaseModel):
    paths: list[str]


class ValidateFoldersResponse(BaseModel):
    valid: bool
    warnings: list[str]
    clean_paths: list[str]


class AddFolderRequest(BaseModel):
    path: str


@router.get("/projects/{name}/scan", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def folder_selector(
    name: str,
    request: Request,
    tab: str = "scan",
    q: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> HTMLResponse:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    folders = await get_scanned_folders_store().list_folders(project)
    # asyncio.to_thread: importar torch (si está instalado) e inicializar CUDA
    # tiene coste no trivial — no debe bloquear el event loop (AUDIT_PLAN GPU).
    gpu_status = await asyncio.to_thread(detect_gpu_status)
    # Mismo motivo que gpu_status: find_spec/shutil.which son baratos, pero se
    # mantiene el mismo patrón (asyncio.to_thread) por consistencia.
    av_status = await asyncio.to_thread(detect_av_status)

    # La pestaña Caché se renderiza siempre en la misma respuesta (igual que el
    # resto de la app: todo server-rendered, sin fragmentos cargados por AJAX) para
    # que el cambio de pestaña sea instantáneo sin recargar la página.
    cache_q = (q.strip() or None) if q else None
    cache_entries, cache_page = await _load_cache_page(project, q=cache_q, page=page, page_size=page_size)

    # Histórico de duración de ejecuciones (tiempo de la última ejecución +
    # pestaña "Historial de ejecuciones"): igual que la pestaña Caché, se carga
    # siempre en la misma respuesta, sin fragmentos cargados por AJAX.
    scan_history = await _load_scan_history(project)
    last_scan_run = scan_history[0] if scan_history else None

    if tab == "cache":
        active_tab = "cache"
    elif tab == "history":
        active_tab = "history"
    else:
        active_tab = "scan"

    return _templates.TemplateResponse(
        request,
        "folder_selector.html.j2",
        {
            "project": project,
            "folders": folders,
            "gpu_status": gpu_status,
            "av_status": av_status,
            "active_tab": active_tab,
            "last_scan_run": last_scan_run,
            "scan_history": scan_history,
            "cache_entries": cache_entries,
            "cache_q": cache_q,
            "cache_page": cache_page.number,
            "cache_page_size": cache_page.size,
            "cache_total": cache_page.total,
            "cache_total_pages": cache_page.total_pages,
            "cache_page_size_options": PAGE_SIZE_OPTIONS,
            "cache_range_start": cache_page.range_start,
            "cache_range_end": cache_page.range_end,
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
            "av_supported_extensions": sorted(AV_SUPPORTED_EXTENSIONS),
        },
    )


@router.get(
    "/api/projects/{name}/folders/library",
    response_model=list[ScannedFolder],
    dependencies=[Depends(require_project_access)],
)
async def list_folder_library(name: str, request: Request) -> list[ScannedFolder]:
    """Lista la carpeta persistente de carpetas guardadas de `name` (menú Escaneo).

    Filtrada por el acceso de escaneo implícito del rol (AUDIT_CODE, sesión
    2026-09-03/04; rediseño Tenant/Role/User: acceso implícito = `project.root_path`
    en vez de `Role.allowed_scan_roots`): sin esto, un rol restringido con acceso
    al proyecto podía ver rutas absolutas completas del servidor guardadas por
    otro usuario/admin fuera de la carpeta del proyecto — mismo criterio que ya se
    aplicaba al dar de alta una carpeta (`add_folder_to_library`).
    """
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    folders = await get_scanned_folders_store().list_folders(project)
    allowed_roots = get_allowed_scan_roots(request, project)
    return [folder for folder in folders if paths_within_roots([folder.path], allowed_roots)]


@router.post(
    "/api/projects/{name}/folders/library",
    response_model=ScannedFolder,
    dependencies=[Depends(require_project_access)],
)
async def add_folder_to_library(name: str, payload: AddFolderRequest, request: Request) -> ScannedFolder:
    """Añade una carpeta a la lista persistente de `name` (botón "Buscar…" del menú Escaneo).

    Sujeto a la misma restricción de acceso implícito que el escaneo en sí — un
    rol restringido no puede guardar en su lista una carpeta fuera de la carpeta
    de trabajo del proyecto (`project.root_path`), que de todos modos no podría
    escanear.
    """
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    allowed_roots = get_allowed_scan_roots(request, project)
    if not paths_within_roots([payload.path], allowed_roots):
        raise HTTPException(status_code=403, detail="No tienes acceso a esa carpeta.")

    return await get_scanned_folders_store().add_folder(project, payload.path)


@router.delete(
    "/api/projects/{name}/folders/library",
    status_code=204,
    dependencies=[Depends(require_project_access)],
)
async def remove_folder_from_library(name: str, payload: AddFolderRequest, request: Request) -> None:
    """Elimina una carpeta no usada de la lista persistente de `name`.

    Sujeta a la misma restricción de acceso implícito que `add_folder_to_library`
    (AUDIT_CODE, sesión 2026-09-03/04): antes un rol restringido podía borrar
    cualquier entrada de la lista (si no estaba `used`) sin que se le exigiera
    acceso a esa ruta.

    Raises:
        HTTPException: 403 si la ruta queda fuera de la carpeta del proyecto para
            un rol restringido; 404 si la carpeta no está en la lista; 409 si ya
            se usó en un escaneo (`ScannedFolderInUseError`, mapeada en `web/app.py`).
    """
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    allowed_roots = get_allowed_scan_roots(request, project)
    if not paths_within_roots([payload.path], allowed_roots):
        raise HTTPException(status_code=403, detail="No tienes acceso a esa carpeta.")

    await get_scanned_folders_store().remove_folder(project, payload.path)


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


@router.websocket("/api/projects/{name}/scan")
async def scan_websocket(name: str, websocket: WebSocket) -> None:
    """Escanea/convierte el proyecto `name`, retransmitiendo cada `ScanEvent` como JSON."""
    await websocket.accept()

    auth_result = await authorize_project_websocket(websocket, name)
    if auth_result is None:
        return
    tenant_id, allowed_scan_roots = auth_result

    operation_key = await acquire_project_operation_lock(websocket, tenant_id, name)
    if operation_key is None:
        return
    try:
        async with get_project_registry(websocket) as registry:
            project = await resolve_ws_project(websocket, registry, name, tenant_id)
        if project is None:
            return

        try:
            request_payload = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            # Payload no-JSON del cliente -- cierre limpio con motivo, mismo patrón
            # que el resto de esta función ante entrada inválida, en vez de dejar
            # escapar la excepción cruda (AUDIT_CODE, sesión 2026-09-03).
            await websocket.close(code=1008, reason="El payload debe ser JSON válido")
            return

        if not isinstance(request_payload, dict):
            await websocket.close(code=1008, reason="El payload debe ser un objeto JSON")
            return

        # Ya no se acepta `paths` del cliente (antes, selección manual por checkbox):
        # se escanean siempre TODAS las carpetas guardadas del proyecto — el cliente ya
        # no elige un subconjunto. `paths_within_roots` se mantiene como defensa en
        # profundidad por si el rol perdió acceso a alguna carpeta ya guardada después
        # de guardarla.
        folders = await get_scanned_folders_store().list_folders(project)
        saved_paths = [folder.path for folder in folders]
        if not saved_paths:
            await websocket.close(code=1008, reason="No hay carpetas guardadas para este proyecto")
            return
        if not paths_within_roots(saved_paths, allowed_scan_roots):
            await websocket.close(code=1008, reason="Forbidden path")
            return

        # Antes, el cliente llamaba a `/folders/validate` y enviaba `clean_paths` en el
        # payload; `mark_used` marcaba exactamente esas rutas ya validadas. Ahora que
        # las rutas vienen del store sin ese preflight, se valida aquí para no marcar
        # como `used` (permanente, ver `ScannedFoldersStore.remove_folder`) una carpeta
        # guardada que `FolderValidator`/`ScanCommand._resolve_scan_paths` descarta por
        # no existir ya en disco.
        paths = FolderValidator().validate_folder_set(saved_paths).clean_paths

        use_ocr = bool(request_payload.get("use_ocr", False))
        use_gpu = bool(request_payload.get("use_gpu", False))
        force = bool(request_payload.get("force", False))
        include_audio_video = bool(request_payload.get("include_audio_video", False))
        extract_images = bool(request_payload.get("extract_images", False))
        use_picture_description = bool(request_payload.get("use_picture_description", False))

        root = Path(project.root_path)
        try:
            async for event in ScanCommand().run_streaming(
                paths=paths,
                output_dir=root / CONVERSION_FOLDER_NAME,
                cache_db=root / DEFAULT_CACHE_DB_NAME,
                folders_json=root / SCAN_FOLDERS_JSON_NAME,
                use_ocr=use_ocr,
                use_gpu=use_gpu,
                force=force,
                include_audio_video=include_audio_video,
                extract_images=extract_images,
                use_picture_description=use_picture_description,
                error_log_path=root / SCAN_ERRORS_FOLDER_NAME / SCAN_ERRORS_HISTORY_JSONL_NAME,
                history_log_path=root / SCAN_HISTORY_FOLDER_NAME / SCAN_HISTORY_JSONL_NAME,
            ):
                if event.event == ScanEventType.COMPLETED:
                    # Se marca ANTES de retransmitir el evento "completed" al cliente
                    # (menú Escaneo, lista persistente de carpetas): el cliente cierra
                    # el WebSocket en cuanto recibe "completed" (ver
                    # folder_selector.html.j2), así que si `mark_used` fuera después
                    # de `send_json` competiría con esa desconexión.
                    await get_scanned_folders_store().mark_used(project, paths)
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            logger.info(f"Cliente desconectado durante el escaneo de '{name}' (tenant '{tenant_id}')")
            return

        await websocket.close()
    finally:
        release_project_operation_lock(websocket, operation_key)


@router.websocket("/api/projects/{name}/scan/deduplicate")
async def deduplicate_websocket(name: str, websocket: WebSocket) -> None:
    """Busca y mueve duplicados sobre TODAS las carpetas guardadas del proyecto
    `name`, a petición del usuario (botón "Buscar duplicados", pestaña
    "Duplicados"), retransmitiendo cada `DedupEvent` como JSON.

    Mismo patrón que `scan_websocket`: sin payload de entrada (a diferencia del
    escaneo, no hay opciones que configurar), autorización + resolución de
    carpetas guardadas compartidas vía `authorize_project_websocket`.
    """
    await websocket.accept()

    auth_result = await authorize_project_websocket(websocket, name)
    if auth_result is None:
        return
    tenant_id, allowed_scan_roots = auth_result

    operation_key = await acquire_project_operation_lock(websocket, tenant_id, name)
    if operation_key is None:
        return
    try:
        async with get_project_registry(websocket) as registry:
            project = await resolve_ws_project(websocket, registry, name, tenant_id)
        if project is None:
            return

        folders = await get_scanned_folders_store().list_folders(project)
        saved_paths = [folder.path for folder in folders]
        if not saved_paths:
            await websocket.close(code=1008, reason="No hay carpetas guardadas para este proyecto")
            return
        if not paths_within_roots(saved_paths, allowed_scan_roots):
            await websocket.close(code=1008, reason="Forbidden path")
            return

        root = Path(project.root_path)
        try:
            async for event in ScanCommand().deduplicate_streaming(
                paths=saved_paths,
                duplicates_dir=root / DUPLICATES_FOLDER_NAME,
                folders_json=root / SCAN_FOLDERS_JSON_NAME,
            ):
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            logger.info(f"Cliente desconectado durante la deduplicación de '{name}' (tenant '{tenant_id}')")
            return

        await websocket.close()
    finally:
        release_project_operation_lock(websocket, operation_key)


__all__ = ["router"]
