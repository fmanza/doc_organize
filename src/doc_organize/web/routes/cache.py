"""
Cache Viewer: lectura de `cache.db`, de solo lectura (Fase D-2c, §2.7.4).
"""

import math

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from markupsafe import Markup, escape
from pydantic import BaseModel

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import CacheEntry, Project
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

_PAGE_SIZE_OPTIONS = (25, 50, 100, 200)
_DEFAULT_PAGE_SIZE = 50


def _dirname(full_path: str) -> str:
    """Carpeta contenedora de `full_path`, para mostrarla separada del nombre de
    archivo en la tabla del Cache Viewer (mismo criterio que en Duplicates Resolver)."""
    return str(Path(full_path).parent)


def _basename(full_path: str) -> str:
    """Nombre de archivo de `full_path`, sin la carpeta contenedora. `CacheEntry` no
    guarda un `display_name` separado (a diferencia de `DocumentMetadata`), así que
    se deriva aquí para la columna "Archivo" del Cache Viewer."""
    return Path(full_path).name


def _highlight(text: str, query: str | None) -> Markup:
    """Envuelve en `<mark>` la subcadena de `text` que coincide (insensible a
    mayúsculas) con `query`. `text` viene de `file_path`, que no lo controla quien
    busca (puede ser el nombre de cualquier archivo del proyecto) — cada fragmento se
    escapa individualmente con `markupsafe.escape()` antes de recomponer el HTML, para
    no reabrir un XSS vía un nombre de archivo malicioso."""
    if not query:
        return escape(text)
    lowered_text = text.lower()
    lowered_query = query.lower()
    start = lowered_text.find(lowered_query)
    if start == -1:
        return escape(text)
    end = start + len(query)
    return Markup("{}<mark>{}</mark>{}").format(text[:start], text[start:end], text[end:])


_templates.env.filters["dirname"] = _dirname
_templates.env.filters["basename"] = _basename
_templates.env.filters["highlight"] = _highlight

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

    entries = [_to_response(entry) for entry in cached.values()]
    return project, entries


def _to_response(entry: CacheEntry) -> CacheEntryResponse:
    return CacheEntryResponse(
        file_path=entry.file_path,
        sha256_hash=entry.sha256_hash,
        timestamp=entry.timestamp,
        status=entry.status.value,
        conversion_status=entry.conversion_status.value if entry.conversion_status else None,
    )


async def _load_project_and_page(
    request: Request, name: str, *, q: str | None, page: int, page_size: int
) -> tuple[Project, list[CacheEntryResponse], int, int]:
    """Carga una página de `cache_entries` para el Cache Viewer.

    Devuelve `page` ya acotada a `[1, total_pages]` (nunca produce un 404 por navegar
    fuera de rango, p. ej. tras reducir `page_size`).
    """
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    cache_db = Path(project.root_path) / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        total = await cache.count_entries(q)
        total_pages = max(1, math.ceil(total / page_size))
        page = min(max(page, 1), total_pages)
        offset = (page - 1) * page_size
        page_entries = await cache.load_cache_page(page_size, offset, q)

    entries = [_to_response(entry) for entry in page_entries]
    return project, entries, total, page


@router.get("/projects/{name}/cache", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def cache_viewer(
    name: str,
    request: Request,
    q: str | None = None,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> HTMLResponse:
    q = (q.strip() or None) if q else None
    page_size = page_size if page_size in _PAGE_SIZE_OPTIONS else _DEFAULT_PAGE_SIZE

    project, entries, total, page = await _load_project_and_page(request, name, q=q, page=page, page_size=page_size)
    total_pages = max(1, math.ceil(total / page_size))

    range_start = 0 if total == 0 else (page - 1) * page_size + 1
    range_end = min(page * page_size, total)

    return _templates.TemplateResponse(
        request,
        "cache_viewer.html.j2",
        {
            "project": project,
            "entries": entries,
            "q": q,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "page_size_options": _PAGE_SIZE_OPTIONS,
            "range_start": range_start,
            "range_end": range_end,
        },
    )


@router.get("/api/projects/{name}/cache", response_model=CacheListResponse, dependencies=[Depends(require_project_access)])
async def get_cache(name: str, request: Request) -> CacheListResponse:
    _, entries = await _load_project_and_entries(request, name)
    return CacheListResponse(entries=entries, total=len(entries))


__all__ = ["router"]
