"""
Escritura atómica de ficheros de texto sin seguir enlaces (L-8e, G31). Módulo interno: no se re-exporta.

Hasta 0.13.0, `context.json`, `DOMAIN.md`, `index.json`, `index.md`, `zensical.toml` y `taxonomy_manifest.md` se
escribían con `write_text` sobre un temporal de nombre fijo (`<fichero>.tmp`) y luego `os.replace`. Si alguien con
acceso al recurso de red ponía un enlace simbólico con ese nombre, la escritura iba a parar al destino del enlace.
Aquí el temporal tiene un nombre aleatorio y se crea en exclusiva (`tempfile.mkstemp`: `O_CREAT | O_EXCL` y
`O_NOFOLLOW` donde existe), en la misma carpeta que el destino para que `os.replace` sea atómico.
"""

import contextlib
import os
import stat
import tempfile

from pathlib import Path


def _current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


_UMASK = _current_umask()
"""Se lee una vez al importar: `os.umask` no tiene lectura sin escritura y cambiarla en cada llamada no es seguro entre hilos."""


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Escribe `content` en `path` de forma atómica, sin escribir nunca a través de un enlace.

    El temporal se crea con nombre aleatorio y en exclusiva en `path.parent`; luego `os.replace` lo pone en su sitio
    (si `path` es un enlace, se sustituye el enlace, nunca su destino). El fichero final conserva los permisos del que
    sustituye, o los habituales (`0o666` menos la umask) si es nuevo: `mkstemp` lo crearía con `0o600`. Si algo falla,
    se borra el temporal.

    Raises:
        OSError: Si no se puede crear, escribir o mover el temporal (el destino queda como estaba).

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> target = Path(tempfile.mkdtemp()) / "a.txt"
        >>> write_text_atomic(target, "hola")
        >>> target.read_text(encoding="utf-8")
        'hola'
    """
    try:
        current = os.lstat(path)
        mode = stat.S_IMODE(current.st_mode) if stat.S_ISREG(current.st_mode) else 0o666 & ~_UMASK
    except FileNotFoundError:
        mode = 0o666 & ~_UMASK

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        # Mismo tratamiento de saltos de línea que `Path.write_text` (lo que se usaba hasta 0.13.0).
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


__all__ = ["write_text_atomic"]
