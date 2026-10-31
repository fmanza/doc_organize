"""
Histórico de duración de cada ejecución de `ScanCommand.run_streaming()`
(`historial_escaneo/SCAN_HISTORY.jsonl`, dentro de la raíz del proyecto).

Mismo patrón append-only que `SCAN_ERRORS_HISTORY.jsonl`
(`ScanCommand._persist_error_report`) y `DEDUP_HISTORY.jsonl`
(`web/routes/duplicates.py`): una línea JSON por ejecución. A diferencia del
histórico de errores (que solo registra ejecuciones con al menos un error),
aquí se registra TODA ejecución -- incluidas las que no llegaron a
`COMPLETED` (`completed=False`) -- porque el objetivo es visibilidad de
tiempos, no gestión de errores.
"""

import asyncio
import json

from pathlib import Path

from pydantic import ValidationError

from doc_organize.core.models import ScanRunReport
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)


async def append_scan_run(history_path: Path, report: ScanRunReport) -> None:
    """Añade `report` como una línea JSON a `history_path` (crea la carpeta
    contenedora si falta). Mismo patrón que `ScanCommand._persist_error_report`:
    el llamador ya resuelve la ruta completa (p. ej.
    `ProjectLayout.scan_history_log`), esta función solo la escribe.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     history_path = Path(tempfile.mkdtemp()) / "SCAN_HISTORY.jsonl"
        ...     report = ScanRunReport(
        ...         scan_run_id="abc123", started_at="2026-01-01T00:00:00+00:00",
        ...         finished_at="2026-01-01T00:00:05+00:00", duration_seconds=5.0,
        ...         total_scanned=3, completed=True,
        ...     )
        ...     await append_scan_run(history_path, report)
        ...     return list_scan_runs(history_path)[0].scan_run_id
        >>> asyncio.run(main())
        'abc123'
    """
    await asyncio.to_thread(history_path.parent.mkdir, parents=True, exist_ok=True)

    def _append() -> None:
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(report.model_dump_json() + "\n")

    await asyncio.to_thread(_append)


def list_scan_runs(history_path: Path) -> list[ScanRunReport]:
    """Lee `history_path` (JSONL, una línea por ejecución) -- devuelve las
    ejecuciones más recientes primero. Mismo criterio de tolerancia a líneas
    corruptas que `web/scan_errors_data.py::load_error_history`: una línea
    inválida se ignora en vez de tumbar la página con un 500.

    Example:
        >>> list_scan_runs(Path("/ruta/que/no/existe/SCAN_HISTORY.jsonl"))
        []
    """
    if not history_path.is_file():
        return []
    reports: list[ScanRunReport] = []
    for raw_line in history_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            reports.append(ScanRunReport.model_validate_json(line))
        except (json.JSONDecodeError, ValidationError):
            logger.warning(f"Línea inválida en '{history_path}'; se ignora.")
    reports.reverse()
    return reports


__all__ = ["append_scan_run", "list_scan_runs"]
