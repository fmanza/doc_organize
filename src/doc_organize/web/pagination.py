"""
Paginación server-side compartida por las páginas con listados largos
(pestaña Caché de Escanear, Proyectos): mismo criterio de página/tamaño de
página en toda la app, en vez de que cada ruta reimplemente el cálculo.
"""

import math

from dataclasses import dataclass

PAGE_SIZE_OPTIONS = (25, 50, 100, 200)
DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class Page:
    """Resultado de paginar `total` elementos en páginas de `size`.

    Attributes:
        number (int): Página resultante, ya acotada a `[1, total_pages]`.
        size (int): Tamaño de página validado (uno de `PAGE_SIZE_OPTIONS`).
        total (int): Total de elementos, sin paginar.
        total_pages (int): Número total de páginas (mínimo 1, aunque `total` sea 0).
        range_start (int): Índice (1-based) del primer elemento mostrado; 0 si `total` es 0.
        range_end (int): Índice (1-based) del último elemento mostrado.
    """

    number: int
    size: int
    total: int
    total_pages: int
    range_start: int
    range_end: int


def resolve_page_size(page_size: int) -> int:
    """Normaliza `page_size` a una opción válida de `PAGE_SIZE_OPTIONS`."""
    return page_size if page_size in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE


def paginate(total: int, page: int, page_size: int) -> Page:
    """Calcula la página resultante y su rango de visualización.

    `page` se acota a `[1, total_pages]` — nunca produce un 404 por navegar
    fuera de rango (p. ej. tras reducir `page_size` con menos páginas disponibles).

    Example:
        >>> result = paginate(total=120, page=1, page_size=50)
        >>> result.total_pages
        3
        >>> result.range_start, result.range_end
        (1, 50)
    """
    size = resolve_page_size(page_size)
    total_pages = max(1, math.ceil(total / size))
    number = min(max(page, 1), total_pages)
    range_start = 0 if total == 0 else (number - 1) * size + 1
    range_end = min(number * size, total)
    return Page(number=number, size=size, total=total, total_pages=total_pages, range_start=range_start, range_end=range_end)


__all__ = ["DEFAULT_PAGE_SIZE", "PAGE_SIZE_OPTIONS", "Page", "paginate", "resolve_page_size"]
