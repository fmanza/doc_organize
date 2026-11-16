"""Bloqueo exclusivo entre procesos con un fichero `<destino>.lock` (1.6.0). Módulo interno: no se re-exporta.

Lo usa el historial del contexto (`context.context_history`) para que dos construcciones del mismo proyecto en procesos
o equipos distintos no intercalen sus líneas ni giren el fichero a la vez. El bloqueo es un fichero creado con
`O_CREAT | O_EXCL`, que se comporta igual en Windows, Linux, SMB y NFSv3+; `fcntl.flock` y `msvcrt.locking` no son
fiables sobre recursos de red.

Un bloqueo cuyo fichero es más viejo que `stale_after` se da por huérfano (proceso muerto) y se rompe. La antigüedad se
mide con el reloj del servidor de ficheros (la `mtime` de un fichero de sondeo recién creado en la misma carpeta), no
con el del equipo local, para que dos equipos con relojes desajustados no rompan un bloqueo vivo.

Un fichero de bloqueo que es un enlace simbólico nunca se sigue: cuenta como un bloqueo ajeno (se espera o, si es viejo,
se rompe el enlace, no su destino). En Windows no existe `O_NOFOLLOW`, así que se comprueba antes de crearlo; queda un
margen mínimo entre la comprobación y la creación.

Riesgo aceptado: si dos procesos deciden a la vez que el mismo bloqueo es huérfano, uno de ellos puede romper el bloqueo
que el otro acaba de tomar. Hace falta un proceso muerto con el bloqueo y dos esperando en el mismo instante; en el peor
caso se intercalan dos líneas del historial, que `list_context_builds` ya descarta como dañadas.
"""

import contextlib
import errno
import os
import socket
import time
import uuid

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)

DEFAULT_TIMEOUT_S = 5.0
"""Espera máxima para tomar el bloqueo; añadir una línea al historial dura milisegundos."""

DEFAULT_STALE_AFTER_S = 60.0
"""Antigüedad a partir de la cual un bloqueo se da por huérfano."""

_POLL_S = 0.05


def lock_path_for(path: Path) -> Path:
    """Ruta del fichero de bloqueo de `path` (`<nombre>.lock` en la misma carpeta)."""
    return path.with_name(f"{path.name}.lock")


def _server_now(folder: Path) -> float:
    """Hora del servidor de ficheros de `folder`: `mtime` de un fichero de sondeo recién creado (o la local si falla)."""
    probe = folder / f".probe-{uuid.uuid4().hex}"
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW, 0o600)
        os.close(fd)
        try:
            return probe.stat().st_mtime
        finally:
            probe.unlink(missing_ok=True)
    except OSError:
        return time.time()


def _break_if_stale(lock: Path, stale_after: float) -> bool:
    """Borra `lock` si es más viejo que `stale_after`; True si lo ha roto (o ya no existía).

    Usa `lstat`: un enlace simbólico (roto o no) se juzga por sí mismo y se rompe el enlace, nunca su destino. Con
    `stat`, un enlace roto parecía «ya no existe» y `_acquire` reintentaba sin fin.
    """
    try:
        before = lock.lstat()
    except FileNotFoundError:
        return True
    age = _server_now(lock.parent) - before.st_mtime
    if age <= stale_after:
        return False
    # Se renombra antes de borrar: solo un proceso gana el rename, y se comprueba que el renombrado es el que se juzgó.
    tombstone = lock.with_name(f"{lock.name}.stale-{uuid.uuid4().hex}")
    try:
        os.rename(lock, tombstone)
    except FileNotFoundError:
        return True
    try:
        after = tombstone.lstat()
        if after.st_mtime_ns != before.st_mtime_ns:
            logger.warning(f"El bloqueo '{lock}' cambió mientras se rompía por huérfano; se libera igualmente.")
    finally:
        tombstone.unlink(missing_ok=True)
    logger.warning(f"Bloqueo huérfano roto en '{lock}' ({age:.0f} s de antigüedad).")
    return True


def _check_deadline(lock: Path, deadline: float, timeout: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(f"No se pudo tomar el bloqueo '{lock}' en {timeout:g} s")


def _wait_or_timeout(lock: Path, deadline: float, timeout: float) -> None:
    _check_deadline(lock, deadline, timeout)
    time.sleep(_POLL_S)


def _create_exclusive(lock: Path) -> int:
    """Crea `lock` en exclusiva sin seguir enlaces; `FileExistsError` si ya existe, también si es un enlace."""
    if os.path.islink(lock):  # Windows: sin O_NOFOLLOW, O_EXCL crearía el destino de un enlace roto
        raise FileExistsError(errno.EEXIST, "El fichero de bloqueo es un enlace simbólico", str(lock))
    return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW, 0o644)


def _acquire(lock: Path, timeout: float, stale_after: float) -> None:
    deadline = time.monotonic() + timeout
    owner = f"{os.getpid()} {socket.gethostname()} {datetime.now(UTC).isoformat()}\n".encode()
    while True:
        try:
            fd = _create_exclusive(lock)
        except FileExistsError:
            if _break_if_stale(lock, stale_after):
                _check_deadline(lock, deadline, timeout)  # acota el bucle aunque algo raro lo repita sin esperar
                continue
            _wait_or_timeout(lock, deadline, timeout)
            continue
        except PermissionError:
            # Windows: crear un fichero que otro proceso está borrando («delete pending», frecuente en SMB) da
            # PermissionError en vez de FileExistsError. Una carpeta de solo lectura acaba igual, tras `timeout`.
            if os.name != "nt":
                raise
            _wait_or_timeout(lock, deadline, timeout)
            continue
        try:
            os.write(fd, owner)
        finally:
            os.close(fd)
        return


@contextlib.contextmanager
def exclusive_lock(path: Path, *, timeout: float = DEFAULT_TIMEOUT_S, stale_after: float = DEFAULT_STALE_AFTER_S) -> Iterator[None]:
    """Bloqueo exclusivo entre procesos sobre `path` mientras dura el bloque `with`. Síncrono: úsalo en un hilo.

    Raises:
        TimeoutError: Si otro proceso mantiene el bloqueo más de `timeout` segundos (es un `OSError`).
        OSError: Si no se puede crear el fichero de bloqueo (carpeta de solo lectura, sin espacio…).

    Example:
        >>> import tempfile
        >>> target = Path(tempfile.mkdtemp()) / "CONTEXT_HISTORY.jsonl"
        >>> with exclusive_lock(target):
        ...     lock_path_for(target).exists()
        True
        >>> lock_path_for(target).exists()
        False
    """
    lock = lock_path_for(path)
    _acquire(lock, timeout, stale_after)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


__all__ = ["DEFAULT_STALE_AFTER_S", "DEFAULT_TIMEOUT_S", "exclusive_lock", "lock_path_for"]
