"""Carga de lo que se exporta (L-7): entradas de una o varias cachés e historial de errores de escaneo.

Un consumidor puede tener varias cachés por proyecto (doc_organize_web guarda una por carpeta de origen, con salidas en
`Conversión/<carpeta>/`), así que todo acepta varias rutas explícitas; nada se deriva del registro de proyectos.
"""

import json

from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from doc_organize.cache import CacheManager
from doc_organize.core.models import CacheEntry, ScanErrorReport
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)


async def load_cache_entries(cache_dbs: Iterable[str | Path]) -> list[CacheEntry]:
    """Entradas de todas las cachés indicadas, en una sola lista.

    Las cachés que no existen se omiten (un proyecto nunca escaneado exporta una instantánea vacía) y no se crean. Si la
    misma ruta aparece en dos cachés, gana la de la última caché.

    Args:
        cache_dbs: Rutas a `cache.db` (p. ej. `[layout.cache_db]` o una por carpeta de origen).

    Returns:
        Las entradas, sin orden garantizado (las funciones de exportación las ordenan).

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> asyncio.run(load_cache_entries([Path(tempfile.mkdtemp()) / "cache.db"]))
        []
    """
    merged: dict[str, CacheEntry] = {}
    for cache_db in cache_dbs:
        path = Path(cache_db)
        if not path.is_file():
            logger.debug(f"Caché inexistente, se omite: '{path}'")
            continue
        async with CacheManager(path) as cache:
            merged.update(await cache.load_cache())
    return list(merged.values())


def load_scan_error_history(history_logs: Iterable[str | Path]) -> list[ScanErrorReport]:
    """Ejecuciones con errores de uno o varios `SCAN_ERRORS_HISTORY.jsonl`, las más recientes primero.

    Lee línea a línea. Una línea inválida (p. ej. un corte a mitad de escritura) se ignora con un aviso, igual que
    `scan_history_store.list_scan_runs`; los ficheros que no existen se omiten.

    Args:
        history_logs: Rutas a los históricos (p. ej. `[layout.scan_errors_log]`).

    Returns:
        Los informes ordenados por `timestamp` descendente; con un solo fichero, en orden inverso de escritura.

    Example:
        >>> load_scan_error_history([])
        []
    """
    reports: list[ScanErrorReport] = []
    for history_log in history_logs:
        path = Path(history_log)
        if not path.is_file():
            continue
        file_reports: list[ScanErrorReport] = []
        with path.open(encoding="utf-8") as lines:
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    file_reports.append(ScanErrorReport.model_validate_json(line))
                except (json.JSONDecodeError, ValidationError):
                    logger.warning(f"Línea inválida en '{path}'; se ignora.")
        file_reports.reverse()
        reports.extend(file_reports)
    # Orden estable: con timestamps iguales se conserva el orden inverso de escritura de cada fichero.
    return sorted(reports, key=lambda report: report.timestamp, reverse=True)


__all__ = ["load_cache_entries", "load_scan_error_history"]
