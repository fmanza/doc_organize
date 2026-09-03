"""
Consultas de errores de escaneo (estado actual en `cache.db` + histórico agrupado
por ejecución en `errores_escaneo/SCAN_ERRORS_HISTORY.jsonl`), compartidas entre
`web/routes/scan_errors.py` (página HTML) y `web/routes/downloads.py` (export a
Excel) — mismo criterio que `web/templating.py`/`web/pagination.py`: un módulo de
`web/` sin depender de FastAPI, no un router.
"""

import json

from pathlib import Path

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

logger = get_logger(__name__)


async def load_current_errors(project: Project) -> list[dict[str, object]]:
    """Ficheros con `conversion_status=ERROR` ahora mismo en `cache.db`: estado
    acumulado y sobrescrito en cada escaneo, no el detalle de una ejecución
    concreta (eso es `load_error_history`)."""
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


def load_error_history(project: Project) -> list[ScanErrorReport]:
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


__all__ = ["load_current_errors", "load_error_history"]
