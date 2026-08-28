"""
Cache Viewer: lectura de `cache.db`, de solo lectura (Fase D-2c, §2.7.4).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.core.models import Project
from doc_organize.web.dependencies import get_project_registry, get_tenant_id

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

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
    async with get_project_registry(request) as registry:
        try:
            project = await registry.get_project(name, tenant_id=get_tenant_id(request))
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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


@router.get("/projects/{name}/cache", response_class=HTMLResponse)
async def cache_viewer(name: str, request: Request) -> HTMLResponse:
    project, entries = await _load_project_and_entries(request, name)
    return _templates.TemplateResponse(request, "cache_viewer.html", {"project": project, "entries": entries})


@router.get("/api/projects/{name}/cache", response_model=CacheListResponse)
async def get_cache(name: str, request: Request) -> CacheListResponse:
    _, entries = await _load_project_and_entries(request, name)
    return CacheListResponse(entries=entries, total=len(entries))


__all__ = ["router"]
