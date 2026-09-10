"""
Export ZIP de un proyecto (Fase D-2c, §2.7.4).
"""

import asyncio
import os
import tempfile
import zipfile

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from doc_organize.cache import CacheManager
from doc_organize.core.constants import CONVERSION_FOLDER_NAME, DEDUP_REPORT_JSON_NAME, DEFAULT_CACHE_DB_NAME, DUPLICATES_FOLDER_NAME
from doc_organize.core.models import CacheEntry, CacheExportSnapshot, DocumentStatus, ScanErrorEntry, ScanErrorReport
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

# Reutiliza las mismas consultas que la página HTML de Errores de Escaneo (no las
# duplica): la vista "Estado actual" y el parseo tolerante a lineas corruptas del
# histórico JSONL solo tienen sentido en un sitio.
from doc_organize.web.scan_errors_data import load_current_errors, load_error_history

router = APIRouter(tags=["downloads"])

_CACHE_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Columnas de fichero compartidas por los distintos exports Excel (cache y errores de
# escaneo describen ambos ficheros del proyecto) — definidas una vez para que
# `_CACHE_XLSX_COLUMNS`/`_SCAN_ERRORS_CURRENT_COLUMNS`/`_SCAN_ERRORS_HISTORY_COLUMNS`
# no puedan divergir entre sí (S1192).
_COL_ARCHIVO = "Archivo"
_COL_CARPETA = "Carpeta"
_COL_RUTA_COMPLETA = "Ruta completa"
_COL_MENSAJE_ERROR = "Mensaje de error"
_COL_REINTENTOS = "Reintentos"
_COL_LIMITE_ALCANZADO = "Límite alcanzado"

_CACHE_XLSX_COLUMNS = (
    _COL_ARCHIVO,
    _COL_CARPETA,
    _COL_RUTA_COMPLETA,
    "Hash SHA-256",
    "Estado",
    "Conversión",
    "Última actualización (UTC)",
)
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _build_export_zip(project_root: Path, cached_entries: dict[str, CacheEntry]) -> Path:
    """Construye el ZIP de export en un fichero temporal del sistema.

    Síncrono a propósito (`zipfile` no es async) — se llama vía `asyncio.to_thread`
    desde la ruta para no bloquear el event loop, mismo patrón que `hashlib.scrypt`
    en `§2.7.2` y `hash_file()` en revisión 3. El temporal vive en el directorio
    temporal del sistema (`tempfile.mkstemp`), nunca dentro de `Conversión/` ni de
    ninguna carpeta servida por otra ruta.
    """
    new_files = [e.file_path for e in cached_entries.values() if e.status is DocumentStatus.NEW]
    modified_files = [e.file_path for e in cached_entries.values() if e.status is DocumentStatus.MODIFIED]
    unchanged_files = [e.file_path for e in cached_entries.values() if e.status is DocumentStatus.UNCHANGED]

    snapshot = CacheExportSnapshot(
        export_timestamp=datetime.now(UTC).isoformat(),
        total_entries=len(cached_entries),
        new_files=new_files,
        modified_files=modified_files,
        unchanged_files=unchanged_files,
        entries=list(cached_entries.values()),
    )

    fd, tmp_path_str = tempfile.mkstemp(suffix=".zip", prefix="doc_organize_export_")
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    conversion_dir = project_root / CONVERSION_FOLDER_NAME
    dedup_report = project_root / DUPLICATES_FOLDER_NAME / DEDUP_REPORT_JSON_NAME

    with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if conversion_dir.is_dir():
            for file_path in conversion_dir.rglob("*"):
                if file_path.is_file():
                    zip_file.write(file_path, arcname=file_path.relative_to(project_root))
        zip_file.writestr("cache_export.json", snapshot.model_dump_json(indent=2))
        if dedup_report.is_file():
            zip_file.write(dedup_report, arcname=dedup_report.relative_to(project_root))

    return tmp_path


def _compute_export_preview(project_root: Path, cached_entries: dict[str, CacheEntry]) -> tuple[int, int]:
    """Cuenta ficheros y suma bytes de lo que incluiría `_build_export_zip()`, sin
    construir el ZIP.

    Espeja las mismas tres fuentes que `_build_export_zip()` (`Conversión/`,
    `cache_export.json`, `DEDUP_REPORT.json`) para que el preview mostrado antes de
    descargar coincida con el contenido real del export. Síncrono a propósito
    (stat de disco) — se llama vía `asyncio.to_thread` desde la ruta, mismo patrón
    que el resto de este módulo.
    """
    file_count = 0
    total_size = 0

    conversion_dir = project_root / CONVERSION_FOLDER_NAME
    if conversion_dir.is_dir():
        for file_path in conversion_dir.rglob("*"):
            if file_path.is_file():
                file_count += 1
                total_size += file_path.stat().st_size

    snapshot = CacheExportSnapshot(
        export_timestamp=datetime.now(UTC).isoformat(),
        total_entries=len(cached_entries),
        new_files=[e.file_path for e in cached_entries.values() if e.status is DocumentStatus.NEW],
        modified_files=[e.file_path for e in cached_entries.values() if e.status is DocumentStatus.MODIFIED],
        unchanged_files=[e.file_path for e in cached_entries.values() if e.status is DocumentStatus.UNCHANGED],
        entries=list(cached_entries.values()),
    )
    file_count += 1
    total_size += len(snapshot.model_dump_json(indent=2).encode("utf-8"))

    dedup_report = project_root / DUPLICATES_FOLDER_NAME / DEDUP_REPORT_JSON_NAME
    if dedup_report.is_file():
        file_count += 1
        total_size += dedup_report.stat().st_size

    return file_count, total_size


@router.get("/downloads/projects/{name}/export-preview", dependencies=[Depends(require_project_access)])
async def export_project_preview(name: str, request: Request) -> dict[str, int]:
    """Nº de ficheros y tamaño total (bytes) que incluiría `export.zip`, sin generarlo.

    Pensado para mostrarse junto al enlace de descarga antes de que el usuario
    pulse: es una instantánea del estado actual del proyecto, no una garantía si
    el proyecto cambia entre esta llamada y la descarga real.
    """
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    project_root = Path(project.root_path)
    cache_db = project_root / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        cached_entries = await cache.load_cache()

    file_count, total_size = await asyncio.to_thread(_compute_export_preview, project_root, cached_entries)
    return {"file_count": file_count, "total_size_bytes": total_size}


@router.get("/downloads/projects/{name}/export.zip", dependencies=[Depends(require_project_access)])
async def export_project(name: str, request: Request) -> FileResponse:
    """Descarga un ZIP con `Conversión/` + `cache_export.json` + `DEDUP_REPORT.json` (si existe).

    No incluye logs: `doc_organize.log` (ver `utils.logging.configure_logging`) es un
    fichero de proceso, compartido por todos los proyectos que gestiona esta
    instancia, no un artefacto por proyecto — no tiene sitio natural dentro de un
    export que es, precisamente, "todo lo de este proyecto".
    """
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    project_root = Path(project.root_path)
    cache_db = project_root / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        cached_entries = await cache.load_cache()

    tmp_path = await asyncio.to_thread(_build_export_zip, project_root, cached_entries)

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"{project.name}-export.zip",
        background=BackgroundTask(os.unlink, tmp_path),
    )


def _excel_safe(value: str) -> str:
    """Neutraliza la inyección de fórmulas en hojas de cálculo (OWASP CSV/Excel
    Formula Injection): `value` viene de un nombre de fichero real, no controlado
    por quien descarga el Excel — un fichero llamado p. ej. `=cmd|'/c calc'!A1`
    se interpretaría como fórmula al abrirlo en Excel/LibreOffice si se escribe tal
    cual. Antepone un `'` cuando `value` empieza por un carácter disparador de
    fórmula; el resto de columnas (`Estado`, `Conversión`) vienen de enums
    controlados por la app y no lo necesitan."""
    if value.startswith(_FORMULA_TRIGGER_CHARS):
        return f"'{value}"
    return value


def _cache_export_row(entry: CacheEntry) -> dict[str, object]:
    """Fila del Excel de `cache.db`, con claves derivadas de `_CACHE_XLSX_COLUMNS`
    (en vez de re-teclearlas) para que ambas no puedan desincronizarse."""
    values = (
        _excel_safe(Path(entry.file_path).name),
        _excel_safe(str(Path(entry.file_path).parent)),
        _excel_safe(entry.file_path),
        entry.sha256_hash,
        entry.status.value,
        entry.conversion_status.value if entry.conversion_status else "",
        datetime.fromtimestamp(entry.timestamp, tz=UTC).isoformat(),
    )
    return dict(zip(_CACHE_XLSX_COLUMNS, values, strict=True))


def _build_cache_export_xlsx(cached_entries: dict[str, CacheEntry]) -> Path:
    """Construye el Excel de export de `cache.db` en un fichero temporal del sistema.

    Síncrono a propósito (`pandas`/`openpyxl` no son async) — se llama vía
    `asyncio.to_thread` desde la ruta, mismo patrón que `_build_export_zip`. Exporta
    SIEMPRE todas las entradas (ignora cualquier filtro `?q=` activo en el Cache
    Viewer, igual criterio que `export_project` para `cache_export.json`), ordenadas
    por `file_path` para un resultado determinista.
    """
    rows = [_cache_export_row(entry) for entry in sorted(cached_entries.values(), key=lambda entry: entry.file_path)]
    frame = pd.DataFrame(rows, columns=list(_CACHE_XLSX_COLUMNS))

    fd, tmp_path_str = tempfile.mkstemp(suffix=".xlsx", prefix="doc_organize_cache_export_")
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    frame.to_excel(tmp_path, sheet_name="Cache", index=False)
    return tmp_path


@router.get("/downloads/projects/{name}/cache-export.xlsx", dependencies=[Depends(require_project_access)])
async def export_cache_xlsx(name: str, request: Request) -> FileResponse:
    """Descarga un Excel (.xlsx) con todas las entradas de `cache.db` del proyecto.

    Ignora cualquier filtro `?q=` activo en el Cache Viewer — siempre exporta el
    contenido íntegro de la caché, con el hash SHA-256 completo (a diferencia de la
    tabla en pantalla, que lo trunca a 12 caracteres).
    """
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    cache_db = Path(project.root_path) / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        cached_entries = await cache.load_cache()

    tmp_path = await asyncio.to_thread(_build_cache_export_xlsx, cached_entries)

    return FileResponse(
        tmp_path,
        media_type=_CACHE_XLSX_MEDIA_TYPE,
        filename=f"{project.name}-cache.xlsx",
        background=BackgroundTask(os.unlink, tmp_path),
    )


_SCAN_ERRORS_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SCAN_ERRORS_CURRENT_COLUMNS = (
    _COL_ARCHIVO,
    _COL_CARPETA,
    _COL_RUTA_COMPLETA,
    _COL_MENSAJE_ERROR,
    _COL_REINTENTOS,
    _COL_LIMITE_ALCANZADO,
)
_SCAN_ERRORS_HISTORY_COLUMNS = (
    "Ejecución (scan_run_id)",
    "Fecha (UTC)",
    _COL_ARCHIVO,
    _COL_CARPETA,
    _COL_RUTA_COMPLETA,
    _COL_MENSAJE_ERROR,
    _COL_REINTENTOS,
    _COL_LIMITE_ALCANZADO,
)


def _scan_error_current_row(item: dict[str, object]) -> dict[str, object]:
    """Fila de la hoja "Estado actual", con claves derivadas de
    `_SCAN_ERRORS_CURRENT_COLUMNS` (ver `_cache_export_row`)."""
    values = (
        _excel_safe(Path(str(item["file_path"])).name),
        _excel_safe(str(Path(str(item["file_path"])).parent)),
        _excel_safe(str(item["file_path"])),
        _excel_safe(str(item["error_message"])),
        item["error_retry_count"],
        "Sí" if item["capped"] else "No",
    )
    return dict(zip(_SCAN_ERRORS_CURRENT_COLUMNS, values, strict=True))


def _scan_error_history_row(report: ScanErrorReport, entry: ScanErrorEntry) -> dict[str, object]:
    """Fila de la hoja "Histórico", con claves derivadas de
    `_SCAN_ERRORS_HISTORY_COLUMNS` (ver `_cache_export_row`)."""
    values = (
        report.scan_run_id,
        report.timestamp,
        _excel_safe(Path(entry.file_path).name),
        _excel_safe(str(Path(entry.file_path).parent)),
        _excel_safe(entry.file_path),
        _excel_safe(entry.error_message),
        entry.error_retry_count,
        "Sí" if entry.capped else "No",
    )
    return dict(zip(_SCAN_ERRORS_HISTORY_COLUMNS, values, strict=True))


def _build_scan_errors_export_xlsx(current_errors: list[dict[str, object]], history: list[ScanErrorReport]) -> Path:
    """Construye el Excel de errores de escaneo en un fichero temporal del sistema,
    con "Estado actual" e "Histórico" como hojas separadas del mismo libro (un único
    `.xlsx`, no dos ficheros) — mismo patrón síncrono que `_build_cache_export_xlsx`,
    llamado vía `asyncio.to_thread` desde la ruta.
    """
    current_rows = [_scan_error_current_row(item) for item in current_errors]
    history_rows = [_scan_error_history_row(report, entry) for report in history for entry in report.entries]
    current_frame = pd.DataFrame(current_rows, columns=list(_SCAN_ERRORS_CURRENT_COLUMNS))
    history_frame = pd.DataFrame(history_rows, columns=list(_SCAN_ERRORS_HISTORY_COLUMNS))

    fd, tmp_path_str = tempfile.mkstemp(suffix=".xlsx", prefix="doc_organize_scan_errors_export_")
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    with pd.ExcelWriter(tmp_path) as writer:
        current_frame.to_excel(writer, sheet_name="Estado actual", index=False)
        history_frame.to_excel(writer, sheet_name="Histórico", index=False)
    return tmp_path


@router.get("/downloads/projects/{name}/scan-errors-export.xlsx", dependencies=[Depends(require_project_access)])
async def export_scan_errors_xlsx(name: str, request: Request) -> FileResponse:
    """Descarga un único Excel (.xlsx) con los errores de escaneo del proyecto:
    "Estado actual" (acumulado en `cache.db`) e "Histórico" (agrupado por ejecución
    de escaneo, `SCAN_ERRORS_HISTORY.jsonl`), como dos hojas del mismo libro.
    """
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        project = await registry.get_project(name, tenant_id=get_tenant_id(request))

    current_errors = await load_current_errors(project)
    history = await asyncio.to_thread(load_error_history, project)

    tmp_path = await asyncio.to_thread(_build_scan_errors_export_xlsx, current_errors, history)

    return FileResponse(
        tmp_path,
        media_type=_SCAN_ERRORS_XLSX_MEDIA_TYPE,
        filename=f"{project.name}-scan-errors.xlsx",
        background=BackgroundTask(os.unlink, tmp_path),
    )


__all__ = ["router"]
