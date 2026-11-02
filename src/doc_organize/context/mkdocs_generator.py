"""
Alias obsoleto de `SiteGenerator` (el sitio de contexto se genera con Zensical desde 0.13.0; se retira en 1.0.0).
"""

import warnings

from doc_organize.context.site_generator import SiteGenerator


class MkDocsGenerator(SiteGenerator):
    """Obsoleto desde 0.13.0, se retira en 1.0.0: usa `SiteGenerator`.

    Es el mismo `SiteGenerator` (escribe `zensical.toml`, ya no `mkdocs.yml`; `generate` devuelve `SiteResult` y lanza
    `SiteBuildError` si no puede construir el sitio); solo añade un `DeprecationWarning` al crearlo.

    Example:
        >>> import warnings
        >>> with warnings.catch_warnings(record=True) as caught:
        ...     warnings.simplefilter("always")
        ...     generator = MkDocsGenerator()
        >>> isinstance(generator, SiteGenerator), caught[0].category.__name__
        (True, 'DeprecationWarning')
    """

    def __init__(self) -> None:
        warnings.warn(
            "MkDocsGenerator está obsoleto desde 0.13.0 y se retira en 1.0.0: usa SiteGenerator (sitio con Zensical).",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__()


__all__ = ["MkDocsGenerator"]
