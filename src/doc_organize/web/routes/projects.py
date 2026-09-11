"""
Rutas de gestión de proyectos (REQ-008 vía HTTP, contrato REQ-007 §8.2).
"""

import asyncio

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from doc_organize.projects import ProjectHistoryCleaner
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import (
    get_auth_store,
    get_project_registry,
    get_tenant_id,
    project_operation_key,
    require_admin,
    require_project_access,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_history_cleaner = ProjectHistoryCleaner()


class CreateProjectRequest(BaseModel):
    name: str
    base_location: str


class ProjectResponse(BaseModel):
    name: str
    root_path: str
    created_at: str


class ProjectListItem(ProjectResponse):
    missing: bool


class ProjectListResponse(BaseModel):
    projects: list[ProjectListItem]


class ProjectImpactSummary(BaseModel):
    file_count: int
    total_size_bytes: int
    has_active_operation: bool


class ConfirmedActionRequest(BaseModel):
    confirm: bool = False


class MoveProjectRequest(BaseModel):
    destination_path: str
    confirm: bool = False


def _acquire_operation_lock(request: Request, tenant_id: str, project_name: str) -> tuple[str, str]:
    """Reserva `(tenant_id, project_name)` para esta petición, o levanta 409 si ya
    hay un escaneo, deduplicación u otra operación de mantenimiento en curso."""
    key = project_operation_key(tenant_id, project_name)
    active = request.app.state.active_project_operations
    if key in active:
        raise HTTPException(status_code=409, detail="Ya hay un escaneo, deduplicación u otra operación en curso para este proyecto.")
    active.add(key)
    return key


def _release_operation_lock(request: Request, key: tuple[str, str]) -> None:
    request.app.state.active_project_operations.discard(key)


def _safe_file_size(path: Path) -> int:
    """Tamaño de `path` en bytes, o 0 si no se puede leer (permisos, enlace roto)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _compute_impact(root: Path) -> tuple[int, int]:
    """Cuenta ficheros y tamaño total (bytes) bajo `root`, para el resumen de impacto.

    No sigue symlinks (mismo criterio que `scanner.document_scanner`, que los trata
    como nodo opaco sin recursión ni hashing): recorrido manual con `iterdir()`, no
    `Path.rglob()`, que antes de Python 3.13 sigue subcarpetas enlazadas por defecto
    (este proyecto soporta `>=3.11`) — sin este cuidado, un enlace simbólico dentro de
    la carpeta del proyecto podría hacer que este recuento (admin, pero solo de
    lectura) recorriera/leyera el tamaño de un árbol arbitrario fuera de `root`.
    """
    file_count = 0
    total_size = 0
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue  # carpeta ilegible (permisos): se omite del recuento
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                pending.append(child)
            elif child.is_file():
                file_count += 1
                total_size += _safe_file_size(child)
    return file_count, total_size


@router.post("", response_model=ProjectResponse, status_code=201, dependencies=[Depends(require_admin)])
async def create_project(payload: CreateProjectRequest, request: Request) -> ProjectResponse:
    # ProjectAlreadyExistsError/ProjectNameError/ProjectError se propagan sin
    # capturar: el handler global de web/app.py (_EXCEPTION_STATUS_CODES) las
    # traduce a 409/422/400 respectivamente.
    tenant_id = get_tenant_id(request)
    async with get_project_registry(request) as registry:
        project = await registry.create_project(payload.name, Path(payload.base_location), tenant_id=tenant_id)
    return ProjectResponse(name=project.name, root_path=project.root_path, created_at=project.created_at)


@router.get("", response_model=ProjectListResponse)
async def list_projects(request: Request) -> ProjectListResponse:
    """Lista los proyectos del tenant, filtrados por acceso (revisión 9).

    Un rol `is_admin` ve todos; un rol restringido solo los de su `project_names`.
    Sin sesión resuelta (loopback/sin auth), no se aplica ningún filtro — mismo
    criterio que `get_tenant_id`.
    """
    async with get_project_registry(request) as registry:
        projects = await registry.list_projects(tenant_id=get_tenant_id(request))

    if getattr(request.state, "is_admin", None) is False:
        async with get_auth_store(request) as store:
            role = await store.get_role(request.state.role_id)
        allowed_names = {allowed.lower() for allowed in role.project_names}
        projects = [project for project in projects if project.name.lower() in allowed_names]

    items = [
        ProjectListItem(
            name=project.name,
            root_path=project.root_path,
            created_at=project.created_at,
            missing=not Path(project.root_path).exists(),
        )
        for project in projects
    ]
    return ProjectListResponse(projects=items)


@router.get("/{name}", response_model=ProjectResponse, dependencies=[Depends(require_project_access)])
async def get_project(name: str, request: Request) -> ProjectResponse:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    return ProjectResponse(name=project.name, root_path=project.root_path, created_at=project.created_at)


@router.get(
    "/{name}/impact",
    response_model=ProjectImpactSummary,
    dependencies=[Depends(require_admin)],
)
async def get_project_impact(name: str, request: Request) -> ProjectImpactSummary:
    """Resumen de impacto de `name` (nº de ficheros y tamaño), para informar al
    usuario antes de confirmar "Vaciar histórico", "Eliminar" o "Mover" en la
    ventana modal de confirmación (admin, REQ-008 gestión de proyectos)."""
    tenant_id = get_tenant_id(request)
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=tenant_id)

    root = Path(project.root_path)
    file_count, total_size_bytes = await asyncio.to_thread(_compute_impact, root) if root.is_dir() else (0, 0)
    key = project_operation_key(tenant_id, name)
    has_active_operation = key in request.app.state.active_project_operations
    return ProjectImpactSummary(file_count=file_count, total_size_bytes=total_size_bytes, has_active_operation=has_active_operation)


@router.post(
    "/{name}/clear-history",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def clear_project_history(name: str, payload: ConfirmedActionRequest, request: Request) -> None:
    """Vacía por completo el histórico y contenido de conversión de `name`
    (caché, historial de escaneo/errores/deduplicación, carpetas guardadas,
    salida de conversión), dejando la carpeta del proyecto vacía — el proyecto
    en sí no se borra del registro (admin, REQ-008).

    Requiere confirmación explícita en el payload (`confirm: true`): la ventana
    modal del cliente no es la única barrera contra un vaciado accidental.

    Raises:
        HTTPException: 400 si `confirm` no es `true`; 409 si hay un escaneo,
            deduplicación u otra operación en curso para este proyecto.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Se requiere confirmación explícita para vaciar el histórico del proyecto.")

    tenant_id = get_tenant_id(request)
    key = _acquire_operation_lock(request, tenant_id, name)
    try:
        async with get_project_registry(request) as registry:
            project = await registry.get_project(name, tenant_id=tenant_id)
        await _history_cleaner.clear(project)
    finally:
        _release_operation_lock(request, key)


@router.delete(
    "/{name}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_project(name: str, payload: ConfirmedActionRequest, request: Request) -> None:
    """Elimina `name` por completo: borra su carpeta de trabajo y lo quita del
    registro (admin, REQ-008). Operación irreversible — no hay papelera.

    Requiere confirmación explícita en el payload (`confirm: true`), igual que
    `clear_project_history`.

    Raises:
        HTTPException: 400 si `confirm` no es `true`; 409 si hay un escaneo,
            deduplicación u otra operación en curso para este proyecto.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Se requiere confirmación explícita para eliminar el proyecto.")

    tenant_id = get_tenant_id(request)
    key = _acquire_operation_lock(request, tenant_id, name)
    try:
        async with get_project_registry(request) as registry:
            await registry.delete_project(name, tenant_id=tenant_id)
    finally:
        _release_operation_lock(request, key)


@router.post(
    "/{name}/move",
    response_model=ProjectResponse,
    dependencies=[Depends(require_admin)],
)
async def move_project(name: str, payload: MoveProjectRequest, request: Request) -> ProjectResponse:
    """Mueve la carpeta raíz de `name` a `<destination_path>/<name>/`, arrastrando
    todo su contenido (caché, histórico, carpetas guardadas, salida de
    conversión — todo vive ya dentro de `root_path`, así que mover la carpeta lo
    mueve todo junto) — admin, REQ-008.

    Requiere confirmación explícita en el payload (`confirm: true`), igual que
    `clear_project_history`/`delete_project`.

    Raises:
        HTTPException: 400 si `confirm` no es `true`; 409 si hay un escaneo,
            deduplicación u otra operación en curso para este proyecto.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Se requiere confirmación explícita para mover el proyecto.")

    tenant_id = get_tenant_id(request)
    key = _acquire_operation_lock(request, tenant_id, name)
    try:
        async with get_project_registry(request) as registry:
            project = await registry.move_project_root(name, payload.destination_path, tenant_id=tenant_id)
        return ProjectResponse(name=project.name, root_path=project.root_path, created_at=project.created_at)
    finally:
        _release_operation_lock(request, key)


__all__ = ["router"]
