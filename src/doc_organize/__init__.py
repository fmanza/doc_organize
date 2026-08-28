"""
Sistema de extracción de contenido de documentos en Markdown y JSON documentación y organización.
"""

from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter, OCRScheduler
from doc_organize.dedup import DeduplicationManager
from doc_organize.projects import ProjectRegistry
from doc_organize.scanner import DocumentScanner
from doc_organize.validators import FolderValidator, ProjectValidator

# web/ se añade aquí cuando se implemente (Fase D del plan).

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "CacheManager",
    "DeduplicationManager",
    "DocumentConverter",
    "DocumentScanner",
    "FolderValidator",
    "OCRScheduler",
    "ProjectRegistry",
    "ProjectValidator",
]
