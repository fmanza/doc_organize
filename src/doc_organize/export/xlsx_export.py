"""Excel de la caché y de los errores de escaneo (L-7, hueco G8 de doc_organize_web).

`openpyxl` (extra `export`) se importa al escribir, no al importar el módulo, y en modo `write_only`: las filas se
vuelcan según se generan. Ese modo guarda el XML de cada hoja en un temporal del sistema (`openpyxl.*.xml`) hasta
`save()`; si la escritura se cancela o falla, aquí se borran en el momento en vez de esperar a que acabe el proceso.

Los valores de texto que vienen de rutas o mensajes de error se protegen contra la inyección de fórmulas (OWASP
CSV/Excel Formula Injection) con `_excel_safe`, igual que hacía la web.
"""

import contextlib
import os
import re

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO

from doc_organize.core.constants import MAX_AUTO_ERROR_RETRIES
from doc_organize.core.exceptions import MissingDependencyError
from doc_organize.core.models import CacheEntry, ConversionStatus, ScanErrorEntry, ScanErrorReport
from doc_organize.core.progress import CancelToken, ProgressCallback, checkpoint
from doc_organize.export._progress import ExportProgress
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

# Columnas de fichero compartidas por las hojas (caché y errores describen ficheros del proyecto): definidas una vez
# para que las cabeceras no puedan divergir entre sí.
_COL_ARCHIVO = "Archivo"
_COL_CARPETA = "Carpeta"
_COL_RUTA_COMPLETA = "Ruta completa"
_COL_MENSAJE_ERROR = "Mensaje de error"
_COL_REINTENTOS = "Reintentos"
_COL_LIMITE_ALCANZADO = "Límite alcanzado"

#: Hoja y cabeceras del Excel de caché.
CACHE_SHEET = "Cache"
CACHE_COLUMNS = (
    _COL_ARCHIVO,
    _COL_CARPETA,
    _COL_RUTA_COMPLETA,
    "Hash SHA-256",
    "Estado",
    "Conversión",
    "Última actualización (UTC)",
)
#: Hojas y cabeceras del Excel de errores de escaneo.
SCAN_ERRORS_CURRENT_SHEET = "Estado actual"
SCAN_ERRORS_HISTORY_SHEET = "Histórico"
SCAN_ERRORS_CURRENT_COLUMNS = (
    _COL_ARCHIVO,
    _COL_CARPETA,
    _COL_RUTA_COMPLETA,
    _COL_MENSAJE_ERROR,
    _COL_REINTENTOS,
    _COL_LIMITE_ALCANZADO,
)
SCAN_ERRORS_HISTORY_COLUMNS = (
    "Ejecución (scan_run_id)",
    "Fecha (UTC)",
    _COL_ARCHIVO,
    _COL_CARPETA,
    _COL_RUTA_COMPLETA,
    _COL_MENSAJE_ERROR,
    _COL_REINTENTOS,
    _COL_LIMITE_ALCANZADO,
)

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")
# Caracteres de control que el formato XLSX no admite (openpyxl lanza `IllegalCharacterError`); mismo patrón que
# `openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE`, copiado para no importar openpyxl al importar el módulo.
_ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")

Row = Sequence[object]


def write_cache_xlsx(
    destination: str | Path | BinaryIO,
    entries: Iterable[CacheEntry],
    *,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> int:
    """Escribe un Excel con todas las entradas de caché (hoja `Cache`), ordenadas por `file_path`.

    Lleva el hash SHA-256 completo. Síncrona: un consumidor async la llama con `asyncio.to_thread`.

    Args:
        destination: Ruta del `.xlsx` (se crea o sobrescribe) o fichero binario abierto para escritura.
        entries: Entradas de una o varias cachés (ver `load_cache_entries`).
        on_progress: Recibe `ProgressEvent(operation="export")` por fila (`started`, `export`, `done`).
        cancel_token: Si se cancela, para entre dos filas.

    Returns:
        Filas de datos escritas (sin la cabecera).

    Raises:
        MissingDependencyError: Falta `openpyxl` (extra `export`).
        OperationCancelledError: Se canceló; si `destination` es una ruta, el fichero parcial se borra.

    Example:
        >>> import io
        >>> write_cache_xlsx(io.BytesIO(), [])
        0
    """
    rows = [_cache_row(entry) for entry in sorted(entries, key=lambda entry: entry.file_path)]
    return _write_workbook(destination, [(CACHE_SHEET, CACHE_COLUMNS, rows)], on_progress, cancel_token)


def write_scan_errors_xlsx(
    destination: str | Path | BinaryIO,
    entries: Iterable[CacheEntry],
    history: Iterable[ScanErrorReport],
    *,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> int:
    """Escribe un Excel de errores de escaneo con dos hojas: `Estado actual` e `Histórico`.

    `Estado actual` son las entradas de caché con `conversion_status=ERROR` (ordenadas por `file_path`); `Histórico`,
    una fila por error de cada ejecución, en el orden de `history` (ver `load_scan_error_history`).

    Args:
        destination: Ruta del `.xlsx` (se crea o sobrescribe) o fichero binario abierto para escritura.
        entries: Entradas de una o varias cachés (ver `load_cache_entries`).
        history: Ejecuciones con errores, normalmente las más recientes primero.
        on_progress: Recibe `ProgressEvent(operation="export")` por fila (`started`, `export`, `done`).
        cancel_token: Si se cancela, para entre dos filas.

    Returns:
        Filas de datos escritas en las dos hojas (sin las cabeceras).

    Raises:
        MissingDependencyError: Falta `openpyxl` (extra `export`).
        OperationCancelledError: Se canceló; si `destination` es una ruta, el fichero parcial se borra.

    Example:
        >>> import io
        >>> write_scan_errors_xlsx(io.BytesIO(), [], [])
        0
    """
    errors = sorted((entry for entry in entries if entry.conversion_status == ConversionStatus.ERROR), key=lambda entry: entry.file_path)
    current_rows = [_scan_error_current_row(entry) for entry in errors]
    history_rows = [_scan_error_history_row(report, entry) for report in history for entry in report.entries]
    sheets = [
        (SCAN_ERRORS_CURRENT_SHEET, SCAN_ERRORS_CURRENT_COLUMNS, current_rows),
        (SCAN_ERRORS_HISTORY_SHEET, SCAN_ERRORS_HISTORY_COLUMNS, history_rows),
    ]
    return _write_workbook(destination, sheets, on_progress, cancel_token)


def _excel_safe(value: str) -> str:
    """Neutraliza la inyección de fórmulas: `value` viene de un nombre de fichero o un mensaje de error reales, no
    controlados por quien abre el Excel. Un fichero llamado p. ej. `=cmd|'/c calc'!A1` se interpretaría como fórmula al
    abrirlo en Excel/LibreOffice si se escribe tal cual: se antepone `'` cuando empieza por un carácter disparador.
    También quita los caracteres de control que XLSX no admite. Las columnas que vienen de enums de la aplicación
    (`Estado`, `Conversión`) no lo necesitan."""
    value = _ILLEGAL_CHARACTERS_RE.sub("", value)
    if value.startswith(_FORMULA_TRIGGER_CHARS):
        return f"'{value}"
    return value


def _file_columns(file_path: str) -> tuple[str, str, str]:
    """Archivo, carpeta y ruta completa, protegidos."""
    path = Path(file_path)
    return _excel_safe(path.name), _excel_safe(str(path.parent)), _excel_safe(file_path)


def _cache_row(entry: CacheEntry) -> Row:
    return (
        *_file_columns(entry.file_path),
        entry.sha256_hash,
        entry.status.value,
        entry.conversion_status.value if entry.conversion_status else "",
        datetime.fromtimestamp(entry.timestamp, tz=UTC).isoformat(),
    )


def _scan_error_current_row(entry: CacheEntry) -> Row:
    return (
        *_file_columns(entry.file_path),
        _excel_safe(entry.error_message or ""),
        entry.error_retry_count,
        "Sí" if entry.error_retry_count >= MAX_AUTO_ERROR_RETRIES else "No",
    )


def _scan_error_history_row(report: ScanErrorReport, entry: ScanErrorEntry) -> Row:
    return (
        _excel_safe(report.scan_run_id),
        _excel_safe(report.timestamp),
        *_file_columns(entry.file_path),
        _excel_safe(entry.error_message),
        entry.error_retry_count,
        "Sí" if entry.capped else "No",
    )


def _openpyxl() -> ModuleType:
    try:
        import openpyxl
    except ImportError as exc:
        raise MissingDependencyError("openpyxl", "export") from exc
    return openpyxl


def _write_workbook(
    destination: str | Path | BinaryIO,
    sheets: Sequence[tuple[str, Sequence[str], Sequence[Row]]],
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> int:
    openpyxl = _openpyxl()
    total = sum(len(rows) for _, _, rows in sheets)
    progress = ExportProgress(on_progress, total, logger)
    path = Path(destination) if isinstance(destination, str | os.PathLike) else None
    workbook = openpyxl.Workbook(write_only=True)
    written = 0
    try:
        progress.emit("started", 0)
        for title, columns, rows in sheets:
            sheet = workbook.create_sheet(title)
            sheet.append(_header(sheet, columns))
            for row in rows:
                checkpoint(cancel_token)
                sheet.append(row)
                written += 1
                progress.emit("export", written)
        checkpoint(cancel_token)
        workbook.save(destination)
    except BaseException:
        _discard_temporary_sheets(workbook)
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    progress.emit("done", written)
    return written


def _header(sheet: Any, columns: Sequence[str]) -> list[Any]:
    """Cabecera en negrita (como la escribía pandas)."""
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    font = Font(bold=True)
    cells = []
    for column in columns:
        cell = WriteOnlyCell(sheet, value=column)
        cell.font = font
        cells.append(cell)
    return cells


def _discard_temporary_sheets(workbook: Any) -> None:
    """Borra los temporales `openpyxl.*.xml` de las hojas `write_only` que no llegaron a guardarse.

    Usa el escritor interno de cada hoja (`_writer`, API privada de openpyxl 3.1): si cambia, no se hace nada y openpyxl
    los borra al terminar el proceso, como antes.
    """
    for sheet in getattr(workbook, "worksheets", []):
        writer = getattr(sheet, "_writer", None)
        if writer is None:
            continue
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            writer.cleanup()


__all__ = [
    "CACHE_COLUMNS",
    "CACHE_SHEET",
    "SCAN_ERRORS_CURRENT_COLUMNS",
    "SCAN_ERRORS_CURRENT_SHEET",
    "SCAN_ERRORS_HISTORY_COLUMNS",
    "SCAN_ERRORS_HISTORY_SHEET",
    "write_cache_xlsx",
    "write_scan_errors_xlsx",
]
