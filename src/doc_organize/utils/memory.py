"""Liberación periódica de memoria durante conversiones largas (G38 / L-16, 1.1.0). Uso interno.

Medidas de 1.1.0 (`tests/integration/test_scan_memory_growth.py`): parte de lo que Docling deja tras cada documento
(árboles lxml de python-docx, imágenes de página de PIL/numpy) queda atrapado en ciclos de referencias. El recolector
de Python se dispara por número de objetos, no por bytes, así que esos ciclos pueden tardar muchos documentos en
liberarse: en Windows, sin recolección explícita, un `.docx` sintético dejaba ~5 MiB por documento y un PDF escaneado
con OCR ~40 MiB. Un `gc.collect()` completo cuesta ~0,35 s con los modelos de Docling cargados (unos 750 000 objetos),
más que convertir un documento pequeño, así que se hace cada `every` documentos y no tras cada uno. En Linux (glibc)
se llama además a `malloc_trim(0)` para devolver al sistema la memoria ya libre del heap.
"""

import ctypes
import ctypes.util
import gc
import sys

from collections.abc import Callable

from doc_organize.utils.logging import get_logger

__all__ = ["MemoryReleaser", "release_memory"]

_logger = get_logger(__name__)

#: Documentos entre dos liberaciones.
DEFAULT_RELEASE_EVERY = 10


def _load_malloc_trim() -> Callable[[int], int] | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        trim: Callable[[int], int] = libc.malloc_trim
    except (OSError, AttributeError):  # musl u otra libc sin malloc_trim
        return None
    return trim


_MALLOC_TRIM = _load_malloc_trim()


def release_memory() -> None:
    """Recolección completa de ciclos y, en Linux con glibc, `malloc_trim(0)`."""
    gc.collect()
    if _MALLOC_TRIM is not None:
        try:
            _MALLOC_TRIM(0)
        except OSError as exc:  # pragma: no cover - libc inesperada
            _logger.debug(f"malloc_trim falló: {exc}")


class MemoryReleaser:
    """Llama a `release_memory()` cada `every` documentos (`after_document`).

    Example:
        >>> releaser = MemoryReleaser(every=2)
        >>> [releaser.after_document() for _ in range(4)]
        [False, True, False, True]
    """

    def __init__(self, every: int = DEFAULT_RELEASE_EVERY) -> None:
        self._every = every
        self._count = 0

    def after_document(self) -> bool:
        """Cuenta un documento y libera memoria si toca. Devuelve si liberó."""
        self._count += 1
        if self._every <= 0 or self._count % self._every:
            return False
        release_memory()
        return True
