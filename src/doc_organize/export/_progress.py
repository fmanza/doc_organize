"""Progreso de las exportaciones (L-7): mismo contrato que `ScanCommand` (`ProgressEvent`, callback que no para nada)."""

import logging

from doc_organize.core.progress import Phase, ProgressCallback, ProgressEvent


class ExportProgress:
    """Emite `ProgressEvent(operation="export")` con `total` unidades (ficheros del ZIP o filas del Excel).

    Un fallo del callback se registra y no interrumpe la exportación, igual que `_ProgressTracker` en
    `scan/scan_command.py`.
    """

    def __init__(self, callback: ProgressCallback | None, total: int, logger: logging.Logger) -> None:
        self._callback = callback
        self._total = total
        self._logger = logger

    def emit(self, phase: Phase, processed: int, current: str | None = None) -> None:
        if self._callback is None:
            return
        try:
            self._callback(ProgressEvent(operation="export", phase=phase, processed=processed, total=self._total, current=current))
        except Exception as exc:  # noqa: BLE001 - un callback del consumidor nunca debe parar la operación
            self._logger.warning(f"El callback de progreso falló: {type(exc).__name__}: {exc}")
