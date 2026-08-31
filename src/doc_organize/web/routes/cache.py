"""
Cache Viewer: lectura de `cache.db`, de solo lectura (Fase D-2c, §2.7.4).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import Project
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _dirname(full_path: str) -> str:
    """Carpeta contenedora de `full_path`, para mostrarla separada del nombre de
    archivo en la tabla del Cache Viewer (mismo criterio que en Duplicates Resolver)."""
    return str(Path(full_path).parent)


def _basename(full_path: str) -> str:
    """Nombre de archivo de `full_path`, sin la carpeta contenedora. `CacheEntry` no
    guarda un `display_name` separado (a diferencia de `DocumentMetadata`), así que
    se deriva aquí para la columna "Archivo" del Cache Viewer."""
    return Path(full_path).name


_templates.env.filters["dirname"] = _dirname
_templates.env.filters["basename"] = _basename

router = APIRouter(tags=["cache"])


class CacheEntryResponse(BaseModel):
    file_path: str
    sha256_hash: str
    timestamp: float
    status: str
    conversion_status: str | None


class CacheListResponse(BaseModel):
    entries: list[CacheEntryResponse]
    total: int


async def _load_project_and_entries(request: Request, name: str) -> tuple[Project, list[CacheEntryResponse]]:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    cache_db = Path(project.root_path) / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        cached = await cache.load_cache()

    entries = [
        CacheEntryResponse(
            file_path=entry.file_path,
            sha256_hash=entry.sha256_hash,
            timestamp=entry.timestamp,
            status=entry.status.value,
            conversion_status=entry.conversion_status.value if entry.conversion_status else None,
        )
        for entry in cached.values()
    ]
    return project, entries


@router.get("/projects/{name}/cache", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def cache_viewer(name: str, request: Request) -> HTMLResponse:
    project, entries = await _load_project_and_entries(request, name)
    return _templates.TemplateResponse(request, "cache_viewer.html.j2", {"project": project, "entries": entries})


@router.get("/api/projects/{name}/cache", response_model=CacheListResponse, dependencies=[Depends(require_project_access)])
async def get_cache(name: str, request: Request) -> CacheListResponse:
    _, entries = await _load_project_and_entries(request, name)
    return CacheListResponse(entries=entries, total=len(entries))


__all__ = ["router"]
