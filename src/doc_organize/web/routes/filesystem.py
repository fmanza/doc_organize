"""
Explorador de carpetas del servidor, para el botón "Buscar…" del menú Escaneo.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from doc_organize.core.models import DirectoryListing
from doc_organize.utils.path_utils import paths_within_roots
from doc_organize.web.dependencies import get_allowed_scan_roots

router = APIRouter(tags=["filesystem"])


@router.get("/api/fs/browse", response_model=DirectoryListing)
async def browse_directory(request: Request, path: str | None = None) -> DirectoryListing:
    """Lista las subcarpetas inmediatas de `path` (por defecto, la carpeta personal del usuario del servidor).

    Sujeto a la misma restricción `allowed_scan_roots` que el WebSocket de
    escaneo (`web/routes/scan.py::scan_websocket`): un rol restringido no puede
    explorar fuera de sus raíces permitidas — no es un privilegio nuevo, ya
    podía escribir cualquiera de esas rutas a mano en el formulario de escaneo.
    """
    candidate = Path(path).expanduser().resolve() if path else Path.home().resolve()
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"La carpeta no existe: {candidate}")

    allowed_roots = await get_allowed_scan_roots(request)
    if not paths_within_roots([str(candidate)], allowed_roots):
        raise HTTPException(status_code=403, detail="No tienes acceso a esa carpeta.")

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
