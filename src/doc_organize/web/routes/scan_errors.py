"""
Errores de Escaneo: estado actual (acumulado en `cache.db`) e histórico agrupado
por ejecución de escaneo (`errores_escaneo/SCAN_ERRORS_HISTORY.jsonl`).
"""

import asyncio
import json

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from doc_organize.cache import CacheManager
from doc_organize.core.constants import (
    DEFAULT_CACHE_DB_NAME,
    MAX_AUTO_ERROR_RETRIES,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_ERRORS_HISTORY_JSONL_NAME,
)
from doc_organize.core.models import ConversionStatus, Project, ScanErrorReport
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access
from doc_organize.web.templating import create_templates

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)


def _dirname(full_path: str) -> str:
    """Carpeta contenedora de `full_path`, mismo criterio que Duplicates Resolver y
    la pestaña Caché de Escanear."""
    return str(Path(full_path).parent)


def _basename(full_path: str) -> str:
    """Nombre de archivo de `full_path`, sin la carpeta contenedora."""
    return Path(full_path).name


_templates.env.filters["dirname"] = _dirname
_templates.env.filters["basename"] = _basename

router = APIRouter(tags=["scan_errors"])


async def _get_project(request: Request, name: str) -> Project:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        return await registry.get_project(name, tenant_id=get_tenant_id(request))


async def _load_current_errors(project: Project) -> list[dict[str, object]]:
    """Ficheros con `conversion_status=ERROR` ahora mismo en `cache.db`: estado
    acumulado y sobrescrito en cada escaneo, no el detalle de una ejecución
    concreta (eso es `_load_error_history`)."""
    cache_db = Path(project.root_path) / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        cached_entries = await cache.load_cache()
    error_entries = sorted(
        (entry for entry in cached_entries.values() if entry.conversion_status == ConversionStatus.ERROR),
        key=lambda entry: entry.file_path,
    )
    return [
        {
            "file_path": entry.file_path,
            "error_message": entry.error_message or "",
            "error_retry_count": entry.error_retry_count,
            "capped": entry.error_retry_count >= MAX_AUTO_ERROR_RETRIES,
        }
        for entry in error_entries
    ]


def _load_error_history(project: Project) -> list[ScanErrorReport]:
    """Lee `errores_escaneo/SCAN_ERRORS_HISTORY.jsonl` — una línea por ejecución de
    `ScanCommand.run_streaming()` que produjo al menos un error — devuelve las
    ejecuciones más recientes primero. Mismo patrón de tolerancia a líneas
    corruptas que `DEDUP_HISTORY.jsonl` (`web/routes/duplicates.py::_load_dedup_history`):
    una línea inválida (p. ej. un crash a mitad de un `write`) se ignora en vez de
    tumbar la página con un 500.
    """
    history_path = Path(project.root_path) / SCAN_ERRORS_FOLDER_NAME / SCAN_ERRORS_HISTORY_JSONL_NAME
    if not history_path.is_file():
        return []
    reports: list[ScanErrorReport] = []
    for raw_line in history_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            reports.append(ScanErrorReport.model_validate_json(line))
        except (json.JSONDecodeError, ValidationError):
            logger.warning(f"Línea inválida en '{history_path}'; se ignora.")
    reports.reverse()
    return reports


@router.get("/projects/{name}/scan-errors", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def scan_errors_page(name: str, request: Request, tab: str = "current") -> HTMLResponse:
    """Muestra los errores de conversión/OCR: estado actual (acumulado en `cache.db`)
    e histórico agrupado por ejecución de escaneo."""
    project = await _get_project(request, name)
    current_errors = await _load_current_errors(project)
    history = await asyncio.to_thread(_load_error_history, project)
    total_history_errors = sum(len(report.entries) for report in history)
    return _templates.TemplateResponse(
        request,
        "scan_errors.html.j2",
        {
            "project": project,
            "current_errors": current_errors,
            "history": history,
            "total_history_errors": total_history_errors,
            "active_tab": "history" if tab == "history" else "current",
        },
    )


__all__ = ["router"]
