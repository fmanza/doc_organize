"""Deduplicación y resolución de conflictos de versión; desde 2.2.0, también por contenido (`ContentDuplicateFinder`)."""

from doc_organize.dedup.content import ContentDocument, ContentDuplicateFinder, ContentDuplicateReport, exclude_from_context
from doc_organize.dedup.deduplication import DeduplicationManager

__all__ = ["ContentDocument", "ContentDuplicateFinder", "ContentDuplicateReport", "DeduplicationManager", "exclude_from_context"]
