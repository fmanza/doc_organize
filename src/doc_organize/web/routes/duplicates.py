"""
Duplicates Resolver: detección y resolución interactiva de duplicados (Fase D-2c, §2.7.4).
"""

import hashlib
import json

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from doc_organize.core.models import DeduplicationReport, DuplicateGroup, Project
from doc_organize.dedup import DeduplicationManager
from doc_organize.scanner import DocumentScanner
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def _format_file_size(size_bytes: int) -> str:
    """Formatea bytes en una unidad legible (p.ej. "1.5 MB") solo para la plantilla
    del Duplicates Resolver — no toca `DocumentMetadata.size_bytes`, que sigue
    exponiendo el valor en bytes sin redondear en la API JSON."""
    size = float(size_bytes)
    unit_index = 0
    while size >= 1024 and unit_index < len(_SIZE_UNITS) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {_SIZE_UNITS[unit_index]}"
    return f"{size:.1f} {_SIZE_UNITS[unit_index]}"


def _dirname(full_path: str) -> str:
    """Carpeta contenedora de `full_path`, para mostrarla separada del nombre de
    archivo en la tabla del Duplicates Resolver."""
    return str(Path(full_path).parent)


_templates.env.filters["file_size"] = _format_file_size
_templates.env.filters["dirname"] = _dirname

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
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        return await registry.get_project(name, tenant_id=get_tenant_id(request))


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


def _load_last_dedup_report(project: Project) -> DeduplicationReport | None:
    """Lee `duplicados/DEDUP_REPORT.json` si el último escaneo se hizo con
    "Deduplicar" activado: en ese caso `ScanCommand._deduplicate` ya movió los
    duplicados fuera de las carpetas escaneadas *durante el propio escaneo*, así
    que un re-escaneo en vivo (`_detect_duplicates`) no encuentra nada — no porque
    no hubiera duplicados, sino porque ya se resolvieron automáticamente. Sin este
    aviso, la página muestra "No se detectaron duplicados" de forma engañosa justo
    después de que el escaneo informara de grupos detectados.
    """
    report_path = Path(project.root_path) / "duplicados" / "DEDUP_REPORT.json"
    if not report_path.is_file():
        return None
    try:
        return DeduplicationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValidationError):
        # `resolve_duplicates()` escribe este fichero con un `write_text` directo
        # (sin escribir-a-temporal-y-renombrar): un crash o disco lleno a mitad de
        # escritura deja un JSON truncado/corrupto. Sin este fallback, cada visita
        # posterior a esta página tumbaría con un 500 en vez de degradar al mismo
        # "No se detectaron duplicados" que se mostraba antes de que este fichero
        # existiera.
        logger.warning(f"'{report_path}' existe pero no es un DEDUP_REPORT.json válido; se ignora.")
        return None


@router.get("/projects/{name}/duplicates", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def duplicates_resolver_page(name: str, request: Request) -> HTMLResponse:
    """Muestra tanto los duplicados pendientes de resolver (re-escaneo en vivo,
    con formulario interactivo) como el detalle de los ya resueltos en el último
    escaneo con "Deduplicar" activado (`DEDUP_REPORT.json`, de solo lectura) —
    ambos bloques son independientes: los archivos duplicados deben verse en la
    página tanto si el re-escaneo en vivo encuentra algo pendiente como si no.
    """
    project = await _get_project(request, name)
    groups = await _detect_duplicates(project)
    groups_with_keys = [
        {"key": _group_key(group), "group": group, "members": [group.canonical_doc, *group.duplicates]}
        for group in groups
    ]
    last_dedup_report = _load_last_dedup_report(project)
    resolved_groups = [
        {"group": group, "members": [group.canonical_doc, *group.duplicates], "kept": group.user_choice or group.canonical_doc}
        for group in (last_dedup_report.groups if last_dedup_report else [])
    ]
    return _templates.TemplateResponse(
        request,
        "duplicates_resolver.html.j2",
        {
            "project": project,
            "groups": groups_with_keys,
            "last_dedup_report": last_dedup_report,
            "resolved_groups": resolved_groups,
        },
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
