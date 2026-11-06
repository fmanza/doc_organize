"""Reintentos ante errores de E/S transitorios (G11, 1.1.0), pensados para carpetas de red.

Un corte breve de un montaje SMB/NFS lanza `OSError` genéricos (`EIO`, `ETIMEDOUT`, `WinError 64`…) que suelen
desaparecer al repetir la operación. Los errores que indican un estado estable del fichero (no existe, no es una
carpeta, ya existe) no se reintentan: repetirlos solo retrasaría el resultado.
"""

import asyncio
import time

from collections.abc import Awaitable, Callable

from doc_organize.utils.logging import get_logger

__all__ = ["is_transient_os_error", "retry_io", "retry_io_async"]

_logger = get_logger(__name__)

#: Errores que no cambian al repetir la operación.
_PERMANENT_ERRORS: tuple[type[OSError], ...] = (FileNotFoundError, NotADirectoryError, IsADirectoryError, FileExistsError)


def is_transient_os_error(exc: BaseException) -> bool:
    """Si `exc` es un `OSError` que puede desaparecer al repetir la operación.

    Mira también la causa encadenada (`raise ... from`), porque `hash_file` envuelve el error original.

    Example:
        >>> is_transient_os_error(OSError(5, "Input/output error"))
        True
        >>> is_transient_os_error(FileNotFoundError("no existe"))
        False
    """
    if not isinstance(exc, OSError):
        return False
    cause = exc.__cause__
    if isinstance(cause, OSError):
        exc = cause
    return not isinstance(exc, _PERMANENT_ERRORS)


def _delay(attempt: int, backoff_s: float) -> float:
    return float(backoff_s * 2**attempt)


def retry_io[T](func: Callable[[], T], *, retries: int, backoff_s: float, what: str) -> T:
    """Ejecuta `func` (síncrona) y la repite hasta `retries` veces ante un `OSError` transitorio.

    Espera `backoff_s`, `2 * backoff_s`, `4 * backoff_s`… entre intentos. Con `retries=0` equivale a llamar a `func`.

    Args:
        func: Operación sin argumentos (usa `functools.partial` o una lambda).
        retries: Reintentos tras el primer intento.
        backoff_s: Espera antes del primer reintento.
        what: Descripción para el log (p. ej. `"hash de '/red/a.pdf'"`).

    Returns:
        Lo que devuelva `func`.

    Raises:
        OSError: El último error, si es permanente o se agotan los reintentos.

    Example:
        >>> retry_io(lambda: 42, retries=2, backoff_s=0, what="prueba")
        42
    """
    attempt = 0
    while True:
        try:
            return func()
        except OSError as exc:
            if attempt >= retries or not is_transient_os_error(exc):
                raise
            delay = _delay(attempt, backoff_s)
            attempt += 1
            _logger.warning(f"Error de E/S en {what} ({exc}); reintento {attempt}/{retries} en {delay:.1f}s")
            time.sleep(delay)


async def retry_io_async[T](func: Callable[[], Awaitable[T]], *, retries: int, backoff_s: float, what: str) -> T:
    """Versión asíncrona de `retry_io`: `func` devuelve un awaitable nuevo en cada intento.

    Example:
        >>> async def leer() -> str:
        ...     return "ok"
        >>> asyncio.run(retry_io_async(leer, retries=1, backoff_s=0, what="prueba"))
        'ok'
    """
    attempt = 0
    while True:
        try:
            return await func()
        except OSError as exc:
            if attempt >= retries or not is_transient_os_error(exc):
                raise
            delay = _delay(attempt, backoff_s)
            attempt += 1
            _logger.warning(f"Error de E/S en {what} ({exc}); reintento {attempt}/{retries} en {delay:.1f}s")
            await asyncio.sleep(delay)
