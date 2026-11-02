"""
Validacion y normalizacion de rutas (punto central anti path-traversal).

Todo el codigo de doc_organize que construye una ruta a partir de una base
y partes controladas por el usuario/documento (nombres de archivo, rutas
relativas) debe pasar por safe_path_join(), en vez de concatenar manualmente.
"""

import errno
import os
import stat

from pathlib import Path

from doc_organize.core.exceptions import InvalidPathError

# Unión de Windows (`stat.IO_REPARSE_TAG_MOUNT_POINT` solo existe en Windows; `st_reparse_tag`, tampoco fuera de él).
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def safe_path_join(base: str | Path, *parts: str) -> Path:
    """Une `parts` a `base` y valida que el resultado no escape de `base`.

    Args:
        base: Directorio raiz permitido.
        *parts: Componentes de ruta relativos a `base`.

    Returns:
        Ruta absoluta y normalizada, garantizada dentro de `base`.

    Raises:
        InvalidPathError: Si el resultado normalizado queda fuera de `base`
            (por ejemplo, por el uso de "..").

    Example:
        >>> safe_path_join("/repo", "docs", "a.pdf").parts[-3:]  # sin unidad: portable Windows/POSIX
        ('repo', 'docs', 'a.pdf')
        >>> safe_path_join("/repo", "..", "etc", "passwd")
        Traceback (most recent call last):
            ...
        doc_organize.core.exceptions.InvalidPathError: ...
    """
    base_resolved = Path(base).resolve()
    candidate = base_resolved.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise InvalidPathError(f"Path traversal detectado: '{candidate}' escapa de '{base_resolved}'") from exc
    return candidate


def ensure_no_symlinks(path: str | Path) -> Path:
    """Comprueba con `lstat`, sin resolver, que ningún tramo existente de `path` sea un enlace simbólico (o una unión
    de Windows) y devuelve la ruta absoluta normalizada (`os.path.abspath`).

    Los tramos que todavía no existen no pueden ser enlaces y no se comprueban (L-11a, hueco G26 de doc_organize_web).

    Raises:
        OSError: (`errno.ELOOP`) si algún tramo es un enlace.

    Example:
        >>> ensure_no_symlinks("/repo/no/existe").parts[-2:]
        ('no', 'existe')
    """
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT:
            raise OSError(errno.ELOOP, "La ruta pasa por un enlace simbólico (no se sigue)", str(current))
    return absolute


def is_subpath(child: str | Path, parent: str | Path) -> bool:
    """Indica si `child` es igual a `parent` o esta anidado dentro de el.

    Usado por FolderValidator (REQ-001) para detectar carpetas redundantes.

    Example:
        >>> is_subpath("/repo/docs", "/repo")
        True
        >>> is_subpath("/repo", "/repo/docs")
        False
    """
    child_resolved = Path(child).resolve()
    parent_resolved = Path(parent).resolve()
    return child_resolved == parent_resolved or parent_resolved in child_resolved.parents


def paths_within_roots(paths: list[str], allowed_roots: list[str] | None) -> bool:
    """`True` si cada ruta de `paths` es (o está dentro de) alguna de `allowed_roots`.

    `allowed_roots=None` significa "sin restricción" (rol admin, o servidor sin
    autenticación) y siempre devuelve `True`. Con una lista (posiblemente vacía),
    un rol restringido sin `allowed_roots` configuradas no puede indicar ninguna
    ruta externa — evita que eluda su `project_names` apuntando el escaneo (o el
    explorador de carpetas) a una ruta arbitraria del servidor. Compartida por
    `web/routes/scan.py` (WebSocket de escaneo) y `web/routes/filesystem.py`
    (explorador de carpetas), que aplican la misma restricción por rol.
    """
    if allowed_roots is None:
        return True
    if not paths:
        return True
    if not allowed_roots:
        return False
    return all(any(is_subpath(path, root) for root in allowed_roots) for path in paths)


__all__ = ["ensure_no_symlinks", "is_subpath", "paths_within_roots", "safe_path_join"]
