"""
Explorador de carpetas del servidor, para el botón "Buscar…" del menú Escaneo.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.core.models import DirectoryListing, Project
from doc_organize.utils.path_utils import paths_within_roots
from doc_organize.web.dependencies import get_allowed_scan_roots, get_project_registry, get_tenant_id, require_project_access

router = APIRouter(tags=["filesystem"])


async def _resolve_browse_project(request: Request, project: str | None) -> Project | None:
    """Resuelve `project` (query param opcional de `browse_directory`) a su
    `Project`, confirmando primero el acceso del rol de la sesión — extraído para
    mantener la complejidad de `browse_directory` bajo control."""
    if project is None:
        return None
    await require_project_access(project, request)
    async with get_project_registry(request) as registry:
        try:
            return await registry.get_project(project, tenant_id=get_tenant_id(request))
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/fs/browse", response_model=DirectoryListing)
async def browse_directory(request: Request, path: str | None = None, project: str | None = None) -> DirectoryListing:
    """Lista las subcarpetas inmediatas de `path` (por defecto, la carpeta personal del usuario del servidor).

    Sujeto a la misma restricción de acceso implícito que el WebSocket de escaneo
    (`web/routes/scan.py::scan_websocket`): un rol restringido no puede explorar
    fuera de la carpeta de trabajo de un proyecto al que tenga acceso — no es un
    privilegio nuevo, ya podía escribir cualquiera de esas rutas a mano en el
    formulario de escaneo.

    Args:
        project: Nombre del proyecto en cuyo contexto se explora (páginas que ya
            saben para qué proyecto es, p.ej. "Carpetas guardadas" del dashboard).
            Para un rol restringido es obligatorio explorar dentro de este
            parámetro: sin él, no hay ninguna ruta permitida (`404` si el rol no
            tiene acceso a `project`; ver `require_project_access`). Un admin o
            una sesión sin restricción (loopback/sin auth) puede omitirlo — mismo
            comportamiento que antes de este parámetro (p.ej. al elegir la
            ubicación de un proyecto nuevo, que todavía no existe).
    """
    resolved_project = await _resolve_browse_project(request, project)
    candidate = Path(path).expanduser().resolve() if path else Path.home().resolve()

    # Autorización ANTES que existencia (AUDIT_CODE, sesión 2026-09-03/04): si el
    # 404 "no existe" se emitiera antes del 403 "sin acceso", un rol restringido
    # podría distinguir "existe pero no tengo acceso" de "no existe" para
    # cualquier ruta absoluta del servidor — un oráculo de existencia de
    # directorios sin necesidad de tener acceso a ellos.
    allowed_roots = get_allowed_scan_roots(request, resolved_project)
    if not paths_within_roots([str(candidate)], allowed_roots):
        raise HTTPException(status_code=403, detail="No tienes acceso a esa carpeta.")

    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"La carpeta no existe: {candidate}")

    entries: list[str] = []
    try:
        children = list(candidate.iterdir())
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"No se puede leer la carpeta: {exc}") from exc
    for child in children:
        try:
            if child.is_dir():
                entries.append(child.name)
        except OSError:
            continue  # entrada ilegible (permisos, enlace roto, etc.): se omite sin romper el listado
    entries.sort(key=str.lower)

    parent = candidate.parent
    parent_path = str(parent) if parent != candidate else None
    if parent_path is not None and not paths_within_roots([parent_path], allowed_roots):
        parent_path = None  # no ofrecer "subir" fuera de las raíces permitidas de un rol restringido

    return DirectoryListing(current_path=str(candidate), parent_path=parent_path, entries=entries)


__all__ = ["router"]
