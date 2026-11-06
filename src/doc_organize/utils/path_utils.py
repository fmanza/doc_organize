"""
Validacion y normalizacion de rutas (punto central anti path-traversal).

Todo el codigo de doc_organize que construye una ruta a partir de una base
y partes controladas por el usuario/documento (nombres de archivo, rutas
relativas) debe pasar por safe_path_join(), en vez de concatenar manualmente.
"""

import errno
import os
import shutil
import stat

from collections.abc import Callable
from pathlib import Path

from doc_organize.core.exceptions import InvalidPathError

# Unión de Windows (`stat.IO_REPARSE_TAG_MOUNT_POINT` solo existe en Windows; `st_reparse_tag`, tampoco fuera de él).
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003

# `dir_fd` + `O_NOFOLLOW` (POSIX): abrir cada tramo sin seguir enlaces y operar relativo a esos descriptores. Sin ellos
# (Windows) queda la comprobación con `lstat` de `ensure_no_symlinks`.
_O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY: int = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW_DIR_FD = (
    bool(_O_NOFOLLOW and _O_DIRECTORY) and {os.open, os.rename, os.unlink, os.stat, os.mkdir} <= os.supports_dir_fd and os.scandir in os.supports_fd
)


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
        if _is_link(st):
            raise OSError(errno.ELOOP, "La ruta pasa por un enlace simbólico (no se sigue)", str(current))
    return absolute


def _is_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT


def ensure_tree_has_no_symlinks(path: str | Path) -> Path:
    """`ensure_no_symlinks` de `path` y, si es una carpeta, de todo lo que contiene (recorrido con `lstat`).

    Raises:
        OSError: (`errno.ELOOP`) si `path`, algún tramo o algún elemento de dentro es un enlace.

    Example:
        >>> ensure_tree_has_no_symlinks("/repo/no/existe").parts[-2:]
        ('no', 'existe')
    """
    absolute = ensure_no_symlinks(path)
    pending = [absolute] if os.path.isdir(absolute) else []
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                st = entry.stat(follow_symlinks=False)
                if _is_link(st):
                    raise OSError(errno.ELOOP, "La ruta pasa por un enlace simbólico (no se sigue)", entry.path)
                if stat.S_ISDIR(st.st_mode):
                    pending.append(Path(entry.path))
    return absolute


def copy_file_nofollow(source: str | Path, target: str | Path, *, overwrite: bool = False) -> None:
    """Copia `source` a `target` (contenido, permisos y fechas, como `shutil.copy2`) sin seguir enlaces simbólicos.

    Ningún tramo de `source` ni de `target` puede ser un enlace, ni `source` otra cosa que un fichero normal. En POSIX
    las dos carpetas se abren tramo a tramo con `O_NOFOLLOW` y se copia relativo a esos descriptores, así que un enlace
    puesto justo antes de copiar tampoco se sigue; en Windows (sin `dir_fd`) queda la comprobación con `lstat`. Mismo
    criterio que la deduplicación desde 0.12.1 (L-11a, G26); lo usa también `Reorganizer` (L-8a, G27).

    Args:
        source: Fichero de origen.
        target: Ruta del fichero de destino (su carpeta debe existir).
        overwrite: Si `target` ya existe (y no es un enlace), se sustituye. Por defecto `False`: `FileExistsError`.

    Raises:
        OSError: `errno.ELOOP` si hay un enlace; `FileExistsError` si `target` existe y no se permite sobrescribir.
    """
    source_abs = ensure_no_symlinks(source)
    target_abs = ensure_no_symlinks(target)
    if _NOFOLLOW_DIR_FD:
        src_dir = _open_dir_nofollow(source_abs.parent)
        try:
            dst_dir = _open_dir_nofollow(target_abs.parent)
            try:
                _copy_nofollow(source_abs, target_abs, src_dir, dst_dir, overwrite=overwrite)
            finally:
                os.close(dst_dir)
        finally:
            os.close(src_dir)
        return
    if not stat.S_ISREG(os.lstat(source_abs).st_mode):
        raise OSError(errno.ELOOP, "El origen no es un fichero normal (no se sigue)", str(source_abs))
    if not overwrite and os.path.lexists(target_abs):
        raise FileExistsError(errno.EEXIST, "El destino ya existe", str(target_abs))
    shutil.copy2(source_abs, target_abs, follow_symlinks=False)


def copy_tree_nofollow(source_dir: str | Path, target_dir: str | Path) -> None:
    """Copia el contenido de la carpeta `source_dir` dentro de `target_dir` (que se crea si falta) sin seguir enlaces.

    Como `shutil.copytree(..., dirs_exist_ok=True)`: los ficheros que ya existan en el destino se sustituyen. Si
    `source_dir`, `target_dir` o cualquier elemento de dentro es un enlace (o algo que no es carpeta ni fichero
    normal), falla con `OSError` sin seguir el enlace; lo copiado hasta ese momento queda en el destino (el llamador
    decide si lo borra). En POSIX se recorre con descriptores abiertos con `O_NOFOLLOW`.

    Raises:
        OSError: `errno.ELOOP` si hay un enlace.
    """
    source_abs = ensure_no_symlinks(source_dir)
    target_abs = ensure_no_symlinks(target_dir)
    target_abs.mkdir(parents=True, exist_ok=True)
    ensure_no_symlinks(target_abs)
    if _NOFOLLOW_DIR_FD:
        src_fd = _open_dir_nofollow(source_abs)
        try:
            dst_fd = _open_dir_nofollow(target_abs)
            try:
                _copy_tree_fd(src_fd, dst_fd, source_abs)
            finally:
                os.close(dst_fd)
        finally:
            os.close(src_fd)
        return
    _copy_tree_lstat(source_abs, target_abs)


def _open_dir_nofollow(path: Path) -> int:
    """Abre el directorio absoluto `path` tramo a tramo con `O_NOFOLLOW` (`ELOOP` si alguno es un enlace)."""
    fd = os.open(path.anchor, os.O_RDONLY | _O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except BaseException:
        os.close(fd)
        raise
    return fd


def _copy_nofollow(source: Path, target: Path, src_dir: int, dst_dir: int, *, overwrite: bool = False) -> None:
    """Copia contenido, permisos y fechas (como `shutil.copy2`) de `source.name` en `src_dir` a `target.name` en
    `dst_dir`, con `O_NOFOLLOW` en los dos; `O_EXCL` en el destino salvo con `overwrite`."""
    with os.fdopen(os.open(source.name, os.O_RDONLY | _O_NOFOLLOW, dir_fd=src_dir), "rb") as src:
        st = os.fstat(src.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise OSError(errno.ELOOP, "El origen no es un fichero normal (no se sigue)", str(source))
        flags = os.O_WRONLY | os.O_CREAT | _O_NOFOLLOW | (os.O_TRUNC if overwrite else os.O_EXCL)
        with os.fdopen(os.open(target.name, flags, 0o600, dir_fd=dst_dir), "wb") as dst:
            try:
                shutil.copyfileobj(src, dst)
                dst.flush()  # antes de fijar las fechas: si no, la escritura al cerrar las cambia
                os.chmod(dst.fileno(), stat.S_IMODE(st.st_mode))
                os.utime(dst.fileno(), ns=(st.st_atime_ns, st.st_mtime_ns))
            except BaseException:
                os.unlink(target.name, dir_fd=dst_dir)
                raise


def _copy_tree_fd(src_fd: int, dst_fd: int, source: Path) -> None:
    """Parte POSIX de `copy_tree_nofollow`: recorre `src_fd` sin seguir enlaces y copia a `dst_fd`."""
    with os.scandir(src_fd) as iterator:
        entries = [(entry.name, entry.stat(follow_symlinks=False)) for entry in iterator]
    for name, st in entries:
        if stat.S_ISDIR(st.st_mode):
            try:
                os.mkdir(name, 0o777, dir_fd=dst_fd)
            except FileExistsError:
                pass
            child_src = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=src_fd)
            try:
                child_dst = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=dst_fd)
                try:
                    _copy_tree_fd(child_src, child_dst, source / name)
                finally:
                    os.close(child_dst)
            finally:
                os.close(child_src)
        elif stat.S_ISREG(st.st_mode):
            _copy_nofollow(source / name, Path(name), src_fd, dst_fd, overwrite=True)
        else:
            raise OSError(errno.ELOOP, "No es una carpeta ni un fichero normal (no se sigue)", str(source / name))


def _copy_tree_lstat(source: Path, target: Path) -> None:
    """Parte sin `dir_fd` (Windows) de `copy_tree_nofollow`: comprobación con `lstat` de cada elemento."""
    with os.scandir(source) as iterator:
        entries = [(entry.name, entry.stat(follow_symlinks=False)) for entry in iterator]
    for name, st in entries:
        if _is_link(st):
            raise OSError(errno.ELOOP, "La ruta pasa por un enlace simbólico (no se sigue)", str(source / name))
        if stat.S_ISDIR(st.st_mode):
            (target / name).mkdir(exist_ok=True)
            ensure_no_symlinks(target / name)
            _copy_tree_lstat(source / name, target / name)
        elif stat.S_ISREG(st.st_mode):
            copy_file_nofollow(source / name, target / name, overwrite=True)
        else:
            raise OSError(errno.ELOOP, "No es una carpeta ni un fichero normal (no se sigue)", str(source / name))


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
    explorador de carpetas) a una ruta arbitraria del servidor. Pensada para
    que un consumidor (escaneo, explorador de carpetas) aplique la misma
    restricción por rol.
    """
    if allowed_roots is None:
        return True
    if not paths:
        return True
    if not allowed_roots:
        return False
    return all(any(is_subpath(path, root) for root in allowed_roots) for path in paths)


def remove_tree(path: str | Path, *, ignore_errors: bool = False) -> None:
    """`shutil.rmtree` que también borra ficheros y carpetas con el atributo de solo lectura de Windows (1.1.1).

    `shutil.copy2` conserva ese atributo, así que una copia de un original de solo lectura (carpeta de red, CD,
    descarga) dejaba `rmtree` en `PermissionError` a mitad de borrado. Se quita el atributo y se reintenta solo en
    ese caso: nunca a través de un enlace o unión (no se toca su destino) ni ante otros errores, que se propagan
    igual que antes. En POSIX el atributo no existe y el comportamiento no cambia.

    Args:
        path: Carpeta a borrar entera.
        ignore_errors: Como en `shutil.rmtree`: no propagar errores (se deja lo que no se pudo borrar).

    Example:
        >>> import os, stat, tempfile
        >>> from pathlib import Path
        >>> folder = Path(tempfile.mkdtemp())
        >>> (folder / "copia.pdf").write_text("x")
        1
        >>> os.chmod(folder / "copia.pdf", stat.S_IREAD)
        >>> remove_tree(folder)
        >>> folder.exists()
        False
    """
    try:
        shutil.rmtree(path, onexc=_clear_readonly_and_retry)
    except OSError:
        if not ignore_errors:
            raise


def _clear_readonly_and_retry(func: Callable[..., object], path: str, exc: BaseException) -> None:
    if not isinstance(exc, PermissionError) or func not in (os.unlink, os.remove, os.rmdir):
        raise exc
    try:
        st = os.lstat(path)
    except OSError:
        raise exc from None
    is_readonly = bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY)
    is_link = stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) != 0
    if not is_readonly or is_link:
        raise exc
    os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWRITE)
    func(path)


def move_tree(source: str | Path, target: str | Path) -> None:
    """Mueve la carpeta `source` a `target` como `shutil.move`, borrando el origen con `remove_tree` (1.1.1).

    En el mismo volumen es un `os.rename`. Entre volúmenes, copia (`copytree` con `symlinks=True`, como
    `shutil.move`) y después borra el origen, también si tiene ficheros de solo lectura.
    """
    try:
        os.rename(source, target)
    except OSError:
        shutil.copytree(source, target, symlinks=True)
        remove_tree(source)


__all__ = [
    "copy_file_nofollow",
    "copy_tree_nofollow",
    "ensure_no_symlinks",
    "ensure_tree_has_no_symlinks",
    "is_subpath",
    "move_tree",
    "paths_within_roots",
    "remove_tree",
    "safe_path_join",
]
