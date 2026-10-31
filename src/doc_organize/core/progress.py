"""Progreso y cancelación cooperativa de operaciones largas (L-2, hueco G2 de doc_organize_web).

Ligero a propósito (sin Docling): un consumidor crea el `CancelToken` en un hilo o proceso y la operación lo consulta
entre dos documentos (o grupos de duplicados). El documento en curso termina siempre; el lote de OCR, que corre en un
hilo, termina el documento que esté procesando.
"""

import threading

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from doc_organize.core.exceptions import OperationCancelledError

Phase = Literal["started", "discovery", "conversion", "ocr", "deduplication", "classification", "reorganize", "site", "done"]


class CancelToken:
    """Petición de parada compartida entre quien lanza la operación y la operación.

    Seguro entre hilos. Una vez cancelado no se puede reactivar.

    Example:
        >>> token = CancelToken()
        >>> token.cancelled
        False
        >>> token.cancel()
        >>> token.cancelled
        True
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Pide parar la operación en el siguiente punto seguro."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Si se ha pedido parar."""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Lanza `OperationCancelledError` si se ha pedido parar.

        Raises:
            OperationCancelledError: Se llamó a `cancel()`.
        """
        if self._event.is_set():
            raise OperationCancelledError("Operación cancelada")


class ProgressEvent(BaseModel):
    """Progreso con unidades, independiente del tipo de evento de cada operación.

    Attributes:
        operation: `scan`, `deduplicate` o `context_build`.
        phase: Fase actual.
        processed: Unidades terminadas en la fase (documentos, grupos).
        total: Unidades de la fase, si se conocen.
        current: Unidad en curso (ruta del documento), si la hay.
    """

    model_config = ConfigDict(frozen=True)

    operation: Literal["scan", "deduplicate", "context_build"]
    phase: Phase
    processed: int = Field(default=0, ge=0)
    total: int | None = Field(default=None, ge=0)
    current: str | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def checkpoint(token: CancelToken | None) -> None:
    """Punto seguro de parada: sin token no hace nada."""
    if token is not None:
        token.raise_if_cancelled()


__all__ = ["CancelToken", "Phase", "ProgressCallback", "ProgressEvent", "checkpoint"]
