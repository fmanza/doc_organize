"""
Duplicates Resolver: detección y resolución interactiva de duplicados (Fase D-2c, §2.7.4).
"""

import hashlib
import json

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.core.models import DuplicateGroup, Project
from doc_organize.dedup import DeduplicationManager
from doc_organize.scanner import DocumentScanner
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(tags=["duplicates"])


class DuplicatesResponse(BaseModel):
    groups: list[DuplicateGroup]


class ResolveDuplicatesRequest(BaseModel):
    resolutions: dict[str, str]  # group_key -> full_path elegido por el usuario


class ResolveDuplicatesResponse(BaseModel):
    moved: int
    groups_resolved: int


def _group_key(group: DuplicateGroup) -> str:
    """Clave estable derivada del contenido del grupo.

    `DuplicateGroup.group_id` (de `DeduplicationManager`) es un `uuid4` nuevo en cada
    llamada a `find_duplicates()` — no sirve para correlacionar el `GET` inicial con
    el re-escaneo que hace el propio `POST /resolve`. Esta clave sí es estable
    mientras el conjunto de archivos del grupo no cambie entre ambas llamadas.
    """
    paths = sorted([group.canonical_doc.full_path, *(d.full_path for d in group.duplicates)])
    return hashlib.sha256("|".join(paths).encode("utf-8")).hexdigest()


async def _get_project(request: Request, name: str) -> Project:
    async with get_project_registry(request) as registry:
        try:
            return await registry.get_project(name, tenant_id=get_tenant_id(request))
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _detect_duplicates(project: Project) -> list[DuplicateGroup]:
    """Relee `folders.json` (escrito por `ScanCommand`, Fase D-1) y vuelve a escanear
    en vivo — sin mover nada. No usa `cache.db`: `CacheEntry` no guarda suficientes
    campos (nombre, tamaño) para reconstruir el `DocumentMetadata` que necesita
    `DeduplicationManager.find_duplicates()`.
    """
    root = Path(project.root_path)
    folders_json = root / "folders.json"
    if not folders_json.is_file():
        raise HTTPException(
            status_code=409,
            detail="Este proyecto todavía no se ha escaneado nunca (no existe folders.json).",
        )

    payload = json.loads(folders_json.read_text(encoding="utf-8"))
    paths = payload.get("paths", [])

    async with DocumentScanner() as scanner:
        scan_result = await scanner.scan_folders(paths)

    return DeduplicationManager().find_duplicates(scan_result.documents)


@router.get("/projects/{name}/duplicates", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def duplicates_resolver_page(name: str, request: Request) -> HTMLResponse:
    project = await _get_project(request, name)
    groups = await _detect_duplicates(project)
    groups_with_keys = [
        {"key": _group_key(group), "group": group, "members": [group.canonical_doc, *group.duplicates]}
        for group in groups
    ]
    return _templates.TemplateResponse(
        request, "duplicates_resolver.html", {"project": project, "groups": groups_with_keys}
    )


@router.get("/api/projects/{name}/duplicates", response_model=DuplicatesResponse, dependencies=[Depends(require_project_access)])
async def get_duplicates(name: str, request: Request) -> DuplicatesResponse:
    project = await _get_project(request, name)
    groups = await _detect_duplicates(project)
    return DuplicatesResponse(groups=groups)


@router.post(
    "/api/projects/{name}/duplicates/resolve",
    response_model=ResolveDuplicatesResponse,
    dependencies=[Depends(require_project_access)],
)
async def resolve_duplicates(name: str, payload: ResolveDuplicatesRequest, request: Request) -> ResolveDuplicatesResponse:
    """Resuelve los duplicados detectados en un re-escaneo propio del servidor.

    Nunca confía en una ruta de archivo enviada por el cliente: `payload.resolutions`
    solo puede seleccionar, por `group_key`, cuál de los miembros de un grupo
    **detectado aquí mismo** se conserva. Una elección que no coincide con ningún
    miembro real del grupo correspondiente se ignora (se loguea, no se aplica) — ver
    AUDIT_PLAN de `§2.7.4` para el hallazgo de seguridad que motiva este diseño.
    """
    project = await _get_project(request, name)
    groups = await _detect_duplicates(project)

    if not groups:
        return ResolveDuplicatesResponse(moved=0, groups_resolved=0)

    resolved_count = 0
    for group in groups:
        chosen_path = payload.resolutions.get(_group_key(group))
        if chosen_path is None:
            continue
        member = next(
            (doc for doc in [group.canonical_doc, *group.duplicates] if doc.full_path == chosen_path),
            None,
        )
        if member is None:
            logger.warning(f"Resolución ignorada: '{chosen_path}' no es miembro del grupo detectado (proyecto '{name}').")
            continue
        group.user_choice = member
        resolved_count += 1

    duplicates_dir = Path(project.root_path) / "duplicados"
    report = await DeduplicationManager().resolve_duplicates(groups, duplicates_dir)
    moved = report.total_exact_duplicates + report.total_version_conflicts
    return ResolveDuplicatesResponse(moved=moved, groups_resolved=resolved_count)


__all__ = ["router"]
