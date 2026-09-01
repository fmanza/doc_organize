"""
Export ZIP de un proyecto (Fase D-2c, §2.7.4).
"""

import asyncio
import os
import tempfile
import zipfile

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import CacheEntry, CacheExportSnapshot, DocumentStatus
from doc_organize.web.dependencies import get_project_registry, get_tenant_id, require_project_access

router = APIRouter(tags=["downloads"])

_CACHE_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CACHE_XLSX_COLUMNS = (
    "Archivo",
    "Carpeta",
    "Ruta completa",
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
        export_timestamp=datetime.now(timezone.utc).isoformat(),
        total_entries=len(cached_entries),
        new_files=new_files,
        modified_files=modified_files,
        unchanged_files=unchanged_files,
        entries=list(cached_entries.values()),
    )

    fd, tmp_path_str = tempfile.mkstemp(suffix=".zip", prefix="doc_organize_export_")
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    conversion_dir = project_root / "Conversión"
    dedup_report = project_root / "duplicados" / "DEDUP_REPORT.json"

    with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if conversion_dir.is_dir():
            for file_path in conversion_dir.rglob("*"):
                if file_path.is_file():
                    zip_file.write(file_path, arcname=file_path.relative_to(project_root))
        zip_file.writestr("cache_export.json", snapshot.model_dump_json(indent=2))
        if dedup_report.is_file():
            zip_file.write(dedup_report, arcname=dedup_report.relative_to(project_root))

    return tmp_path


@router.get("/downloads/projects/{name}/export.zip", dependencies=[Depends(require_project_access)])
async def export_project(name: str, request: Request) -> FileResponse:
    """Descarga un ZIP con `Conversión/` + `cache_export.json` + `DEDUP_REPORT.json` (si existe).

    No incluye logs: hoy ningún módulo invoca `get_logger(log_file=...)`, así que no
    existe ningún fichero de log por proyecto que empaquetar (recorte explícito del
    DoD original, `§2.7.4`).
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


def _build_cache_export_xlsx(cached_entries: dict[str, CacheEntry]) -> Path:
    """Construye el Excel de export de `cache.db` en un fichero temporal del sistema.

    Síncrono a propósito (`pandas`/`openpyxl` no son async) — se llama vía
    `asyncio.to_thread` desde la ruta, mismo patrón que `_build_export_zip`. Exporta
    SIEMPRE todas las entradas (ignora cualquier filtro `?q=` activo en el Cache
    Viewer, igual criterio que `export_project` para `cache_export.json`), ordenadas
    por `file_path` para un resultado determinista.
    """
    rows = [
        {
            "Archivo": _excel_safe(Path(entry.file_path).name),
            "Carpeta": _excel_safe(str(Path(entry.file_path).parent)),
            "Ruta completa": _excel_safe(entry.file_path),
            "Hash SHA-256": entry.sha256_hash,
            "Estado": entry.status.value,
            "Conversión": entry.conversion_status.value if entry.conversion_status else "",
            "Última actualización (UTC)": datetime.fromtimestamp(entry.timestamp, tz=timezone.utc).isoformat(),
        }
        for entry in sorted(cached_entries.values(), key=lambda entry: entry.file_path)
    ]
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


__all__ = ["router"]
