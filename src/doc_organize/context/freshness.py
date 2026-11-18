"""
Frescura del contexto (2.0.0, F4): qué originales cambiaron, aparecieron o desaparecieron desde la última construcción.

`diff_contexts` compara dos contextos ya construidos; esto compara el contexto con la **caché del último escaneo**,
antes de reconstruir. No lee originales ni `.json`: solo la caché y el contexto, así que se puede llamar en cada carga
de una página.
"""

import os

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from doc_organize.core.models import CacheEntry, Context, ConversionStatus, DocumentStatus, FreshnessReport, Project
from doc_organize.projects.layout import ProjectLayout


def check_context_freshness(
    project: Project,
    context: Context,
    cache_entries: Iterable[CacheEntry],
    *,
    site_dir: Path | None = None,
    scanned_at: str | None = None,
) -> FreshnessReport:
    """Compara el contexto de `project` con las entradas de su caché.

    Un original **cuenta como convertido** si su entrada de caché tiene la conversión terminada con éxito y no está
    marcado como borrado. Los documentos del contexto (clasificados y sin clasificar) se comparan por `source_path`
    y su `source_sha256` con el `sha256_hash` de la caché.

    Args:
        project: Proyecto (para encontrar el sitio).
        context: Contexto construido (`ContextRegistry.load_context`).
        cache_entries: Entradas de las cachés del proyecto (`doc_organize.export.load_cache_entries`).
        site_dir: Carpeta del sitio, si no es la de por defecto (la misma que se pasó a `SiteGenerator.generate`).
        scanned_at: Fecha del último escaneo, si la sabe quien llama: se devuelve en el informe (la comprobación es
            tan reciente como la caché).

    Returns:
        `FreshnessReport` con `changed`, `added`, `removed`, `unknown` y `stale_site`.

    Example:
        >>> from doc_organize.core.models import CacheEntry, Context, ConversionStatus, DocumentStatus, Project
        >>> entry = CacheEntry(file_path="/p/a.pdf", sha256_hash="ab" * 32, timestamp=0.0, status=DocumentStatus.UNCHANGED,
        ...                    conversion_status=ConversionStatus.SUCCESS)
        >>> context = Context(project_name="P", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00")
        >>> check_context_freshness(Project(name="P", root_path="/p", created_at="x"), context, [entry]).added
        ['/p/a.pdf']
    """
    converted = {
        entry.file_path: entry.sha256_hash
        for entry in cache_entries
        if entry.conversion_status == ConversionStatus.SUCCESS and entry.status != DocumentStatus.DELETED
    }
    in_context = {document.source_path: document.source_sha256 for domain in context.domains for document in domain.documents}
    in_context.update({detail.source_path: detail.source_sha256 for detail in context.unclassified_details})

    changed, removed, unknown = [], [], []
    for source_path, fingerprint in in_context.items():
        current = converted.get(source_path)
        if current is None:
            removed.append(source_path)
        elif fingerprint is None:
            unknown.append(source_path)
        elif fingerprint != current:
            changed.append(source_path)
    return FreshnessReport(
        changed=sorted(changed),
        added=sorted(path for path in converted if path not in in_context),
        removed=sorted(removed),
        unknown=sorted(unknown),
        stale_site=_site_is_older(project, context, site_dir),
        scanned_at=scanned_at,
    )


def _site_is_older(project: Project, context: Context, site_dir: Path | None) -> bool:
    """`True` si hay un sitio construido y es anterior a la última construcción del contexto."""
    layout = ProjectLayout.for_project(project)
    directory = layout.site_dir if site_dir is None else Path(site_dir)
    if not directory.is_absolute():
        directory = Path(layout.output_root) / directory
    index = directory / "index.html"
    try:
        built = os.stat(index).st_mtime
        rebuilt = datetime.fromisoformat(context.updated_at).timestamp()
    except (OSError, ValueError):
        return False
    return built < rebuilt


__all__ = ["check_context_freshness"]
