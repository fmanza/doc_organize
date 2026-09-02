"""
Cache API: lectura de `cache.db`, de solo lectura (Fase D-2c, §2.7.4).

La página HTML del Cache Viewer se fusionó en la pestaña "Caché" de la página
Escanear (`web/routes/scan.py`, reestructuración de navegación); este módulo
conserva únicamente el endpoint JSON, usado potencialmente por herramientas
externas.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import CacheEntry, Project
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

router = APIRouter(tags=["cache"])


class CacheEntryResponse(BaseModel):
    file_path: str
    sha256_hash: str
    timestamp: float
    status: str
    conversion_status: str | None
    error_message: str | None


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

    entries = [cache_entry_to_response(entry) for entry in cached.values()]
    return project, entries


def cache_entry_to_response(entry: CacheEntry) -> CacheEntryResponse:
    return CacheEntryResponse(
        file_path=entry.file_path,
        sha256_hash=entry.sha256_hash,
        timestamp=entry.timestamp,
        status=entry.status.value,
        conversion_status=entry.conversion_status.value if entry.conversion_status else None,
        error_message=entry.error_message,
    )


@router.get("/api/projects/{name}/cache", response_model=CacheListResponse, dependencies=[Depends(require_project_access)])
async def get_cache(name: str, request: Request) -> CacheListResponse:
    _, entries = await _load_project_and_entries(request, name)
    return CacheListResponse(entries=entries, total=len(entries))


__all__ = ["router"]
