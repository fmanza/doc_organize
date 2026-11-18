"""Ayudas de los tests para construir manifiestos de taxonomía 2.0 (ejes) con la forma de 1.x."""

from doc_organize.core.models import TaxonomyAxis, TaxonomyEntry, TaxonomyManifest


def two_axis_manifest(
    domains: list[TaxonomyEntry],
    material_types: list[TaxonomyEntry],
    *,
    title: str | None = None,
    description: str | None = None,
    extra_axes: list[TaxonomyAxis] | None = None,
) -> TaxonomyManifest:
    """Manifiesto con el eje `domains` (carpeta), el eje `material_types` (subcarpeta) y, si se dan, más ejes."""
    return TaxonomyManifest(
        title=title,
        description=description,
        axes=[
            TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=domains),
            TaxonomyAxis(key="material_types", name="Tipos de material", organizes="subfolder", entries=material_types),
            *(extra_axes or []),
        ],
    )
