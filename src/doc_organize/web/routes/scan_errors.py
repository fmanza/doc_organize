"""
Errores de Escaneo: estado actual (acumulado en `cache.db`) e histórico agrupado
por ejecución de escaneo (`errores_escaneo/SCAN_ERRORS_HISTORY.jsonl`).
"""

import asyncio

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from doc_organize.core.models import Project
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access
from doc_organize.web.scan_errors_data import load_current_errors, load_error_history
from doc_organize.web.templating import create_templates

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


@router.get("/projects/{name}/scan-errors", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def scan_errors_page(name: str, request: Request, tab: str = "current") -> HTMLResponse:
    """Muestra los errores de conversión/OCR: estado actual (acumulado en `cache.db`)
    e histórico agrupado por ejecución de escaneo."""
    project = await _get_project(request, name)
    current_errors = await load_current_errors(project)
    history = await asyncio.to_thread(load_error_history, project)
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
