"""
Validacion y normalizacion de rutas (punto central anti path-traversal).

Todo el codigo de doc_organize que construye una ruta a partir de una base
y partes controladas por el usuario/documento (nombres de archivo, rutas
relativas) debe pasar por safe_path_join(), en vez de concatenar manualmente.
"""

from pathlib import Path

from doc_organize.core.exceptions import InvalidPathError


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
        >>> safe_path_join("/repo", "docs", "a.pdf")
        WindowsPath('/repo/docs/a.pdf')
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


__all__ = ["is_subpath", "paths_within_roots", "safe_path_join"]
