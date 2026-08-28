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


__all__ = ["safe_path_join", "is_subpath"]
