"""
Export ZIP de un proyecto (Fase D-2c, §2.7.4).

Desde la 0.11.0 la lógica vive en `doc_organize.export` (L-7); este router solo resuelve el proyecto, carga la caché
y sirve un temporal del sistema que se borra tras enviarse.
"""

import asyncio
import os
import tempfile

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from doc_organize.core.models import Project
from doc_organize.export import load_cache_entries, preview_project_zip, write_cache_xlsx, write_project_zip, write_scan_errors_xlsx
from doc_organize.projects.layout import ProjectLayout
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

# Reutiliza el parseo tolerante a líneas corruptas del histórico JSONL de la página HTML de Errores de Escaneo.
from doc_organize.web.scan_errors_data import load_error_history

router = APIRouter(tags=["downloads"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _get_project(name: str, request: Request) -> Project:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        return await registry.get_project(name, tenant_id=get_tenant_id(request))


def _temporary_path(suffix: str, prefix: str) -> Path:
    """Temporal del directorio del sistema, nunca dentro de `Conversión/` ni de otra carpeta servida."""
    fd, tmp_path_str = tempfile.mkstemp(suffix=suffix, prefix=prefix)
    os.close(fd)
    return Path(tmp_path_str)


@router.get("/downloads/projects/{name}/export-preview", dependencies=[Depends(require_project_access)])
async def export_project_preview(name: str, request: Request) -> dict[str, int]:
    """Nº de ficheros y tamaño total (bytes) que incluiría `export.zip`, sin generarlo.

    Pensado para mostrarse junto al enlace de descarga antes de que el usuario
    pulse: es una instantánea del estado actual del proyecto, no una garantía si
    el proyecto cambia entre esta llamada y la descarga real.
    """
    project = await _get_project(name, request)
    layout = ProjectLayout.for_project(project)
    entries = await load_cache_entries([layout.cache_db])

    stats = await asyncio.to_thread(preview_project_zip, entries, layout=layout)
    return {"file_count": stats.file_count, "total_size_bytes": stats.total_size_bytes}


@router.get("/downloads/projects/{name}/export.zip", dependencies=[Depends(require_project_access)])
async def export_project(name: str, request: Request) -> FileResponse:
    """Descarga un ZIP con `Conversión/` + `cache_export.json` + `DEDUP_REPORT.json` (si existe).

    No incluye logs: `doc_organize.log` (ver `utils.logging.configure_logging`) es un
    fichero de proceso, compartido por todos los proyectos que gestiona esta
    instancia, no un artefacto por proyecto — no tiene sitio natural dentro de un
    export que es, precisamente, "todo lo de este proyecto".
    """
    project = await _get_project(name, request)
    layout = ProjectLayout.for_project(project)
    entries = await load_cache_entries([layout.cache_db])

    tmp_path = _temporary_path(".zip", "doc_organize_export_")
    await asyncio.to_thread(write_project_zip, tmp_path, entries, layout=layout)

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"{project.name}-export.zip",
        background=BackgroundTask(os.unlink, tmp_path),
    )


@router.get("/downloads/projects/{name}/cache-export.xlsx", dependencies=[Depends(require_project_access)])
async def export_cache_xlsx(name: str, request: Request) -> FileResponse:
    """Descarga un Excel (.xlsx) con todas las entradas de `cache.db` del proyecto.

    Ignora cualquier filtro `?q=` activo en el Cache Viewer — siempre exporta el
    contenido íntegro de la caché, con el hash SHA-256 completo (a diferencia de la
    tabla en pantalla, que lo trunca a 12 caracteres).
    """
    project = await _get_project(name, request)
    entries = await load_cache_entries([ProjectLayout.for_project(project).cache_db])

    tmp_path = _temporary_path(".xlsx", "doc_organize_cache_export_")
    await asyncio.to_thread(write_cache_xlsx, tmp_path, entries)

    return FileResponse(
        tmp_path,
        media_type=_XLSX_MEDIA_TYPE,
        filename=f"{project.name}-cache.xlsx",
        background=BackgroundTask(os.unlink, tmp_path),
    )


@router.get("/downloads/projects/{name}/scan-errors-export.xlsx", dependencies=[Depends(require_project_access)])
async def export_scan_errors_xlsx(name: str, request: Request) -> FileResponse:
    """Descarga un único Excel (.xlsx) con los errores de escaneo del proyecto:
    "Estado actual" (acumulado en `cache.db`) e "Histórico" (agrupado por ejecución
    de escaneo, `SCAN_ERRORS_HISTORY.jsonl`), como dos hojas del mismo libro.
    """
    project = await _get_project(name, request)
    entries = await load_cache_entries([ProjectLayout.for_project(project).cache_db])
    history = await asyncio.to_thread(load_error_history, project)

    tmp_path = _temporary_path(".xlsx", "doc_organize_scan_errors_export_")
    await asyncio.to_thread(write_scan_errors_xlsx, tmp_path, entries, history)

    return FileResponse(
        tmp_path,
        media_type=_XLSX_MEDIA_TYPE,
        filename=f"{project.name}-scan-errors.xlsx",
        background=BackgroundTask(os.unlink, tmp_path),
    )


__all__ = ["router"]
