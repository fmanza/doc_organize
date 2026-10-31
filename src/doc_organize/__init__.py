"""
Sistema de extracción de contenido de documentos en Markdown y JSON documentación y organización.

API pública (SemVer): los nombres de ``__all__``. Se importan **bajo demanda** (PEP 562): ``import doc_organize`` o
``import doc_organize.utils.<módulo>`` no carga Docling ni torch hasta que se usa un nombre que los necesita (por
ejemplo ``ScanCommand`` o ``DocumentConverter``). Ver ``docs/api/publica.md``.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

try:
    __version__ = version("doc_organize")
except PackageNotFoundError:  # pragma: no cover - solo al ejecutar desde el árbol de fuentes sin instalar
    __version__ = "0.0.0"

#: Nombre público → módulo que lo define. Solo se importa el módulo al acceder al nombre.
_EXPORTS: dict[str, str] = {
    # Puntos de entrada
    "CacheManager": "doc_organize.cache.cache_manager",
    "DocumentConverter": "doc_organize.converter.converter",
    "OCRScheduler": "doc_organize.converter.ocr_scheduler",
    "DeduplicationManager": "doc_organize.dedup.deduplication",
    "DocumentScanner": "doc_organize.scanner.document_scanner",
    "ScanCommand": "doc_organize.scan.scan_command",
    "ScanOptions": "doc_organize.core.models",
    "CancelToken": "doc_organize.core.progress",
    "ProgressEvent": "doc_organize.core.progress",
    "ScanSummary": "doc_organize.scan.scan_command",
    "DeduplicationSummary": "doc_organize.scan.scan_command",
    "ContextBuilder": "doc_organize.context.context_builder",
    "ContextRegistry": "doc_organize.context.context_registry",
    "Reorganizer": "doc_organize.context.reorganizer",
    "MkDocsGenerator": "doc_organize.context.mkdocs_generator",
    "TaxonomyTemplateRegistry": "doc_organize.context.taxonomy_template_registry",
    "ProjectRegistry": "doc_organize.projects.project_registry",
    "ProjectLayout": "doc_organize.projects.layout",
    "ProjectHistoryCleaner": "doc_organize.projects.project_history_cleaner",
    "ScannedFoldersStore": "doc_organize.projects.scanned_folders_store",
    "FolderValidator": "doc_organize.validators.folder_validator",
    "ProjectValidator": "doc_organize.validators.project_validator",
    # Diagnóstico de la instancia (ligeros: no cargan Docling)
    "detect_gpu_status": "doc_organize.utils.gpu_detector",
    "detect_av_status": "doc_organize.utils.av_detector",
    "detect_office_status": "doc_organize.utils.office_detector",
    # Eventos de progreso
    "ScanEvent": "doc_organize.core.models",
    "ScanEventType": "doc_organize.core.models",
    "DedupEvent": "doc_organize.core.models",
    "DedupEventType": "doc_organize.core.models",
    "ContextBuildEvent": "doc_organize.core.models",
    "ContextBuildEventType": "doc_organize.core.models",
    "ContextDeleteEvent": "doc_organize.core.models",
    "ContextDeleteEventType": "doc_organize.core.models",
    # Modelos
    "DocumentMetadata": "doc_organize.core.models",
    "ConversionResult": "doc_organize.core.models",
    "DuplicateGroup": "doc_organize.core.models",
    "DuplicateReason": "doc_organize.core.models",
    "DeduplicationReport": "doc_organize.core.models",
    "CacheEntry": "doc_organize.core.models",
    "ScanErrorEntry": "doc_organize.core.models",
    "ScanErrorReport": "doc_organize.core.models",
    "ScanRunReport": "doc_organize.core.models",
    "ScanResult": "doc_organize.core.models",
    "Project": "doc_organize.core.models",
    "ScannedFolder": "doc_organize.core.models",
    "GpuStatus": "doc_organize.core.models",
    "AvStatus": "doc_organize.core.models",
    "OfficeStatus": "doc_organize.core.models",
    "Context": "doc_organize.core.models",
    "TaxonomyManifest": "doc_organize.core.models",
    # Errores
    "DocOrganizeError": "doc_organize.core.exceptions",
    "OperationCancelledError": "doc_organize.core.exceptions",
    "InvalidPathError": "doc_organize.core.exceptions",
    "ConversionError": "doc_organize.core.exceptions",
    "CacheError": "doc_organize.core.exceptions",
    "ProjectError": "doc_organize.core.exceptions",
    "ProjectNotFoundError": "doc_organize.core.exceptions",
    "ContextError": "doc_organize.core.exceptions",
}

__all__ = ["__version__", *sorted(_EXPORTS)]


def __getattr__(name: str) -> Any:
    """Importa bajo demanda el módulo que define ``name`` (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'doc_organize' has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value  # las siguientes consultas no pasan por aquí
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:  # pragma: no cover - solo para analizadores estáticos (mypy, IDE)
    from doc_organize.cache.cache_manager import CacheManager
    from doc_organize.context.context_builder import ContextBuilder
    from doc_organize.context.context_registry import ContextRegistry
    from doc_organize.context.mkdocs_generator import MkDocsGenerator
    from doc_organize.context.reorganizer import Reorganizer
    from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry
    from doc_organize.converter.converter import DocumentConverter
    from doc_organize.converter.ocr_scheduler import OCRScheduler
    from doc_organize.core.exceptions import (
        CacheError,
        ContextError,
        ConversionError,
        DocOrganizeError,
        InvalidPathError,
        OperationCancelledError,
        ProjectError,
        ProjectNotFoundError,
    )
    from doc_organize.core.models import (
        AvStatus,
        CacheEntry,
        Context,
        ContextBuildEvent,
        ContextBuildEventType,
        ContextDeleteEvent,
        ContextDeleteEventType,
        ConversionResult,
        DedupEvent,
        DedupEventType,
        DeduplicationReport,
        DocumentMetadata,
        DuplicateGroup,
        DuplicateReason,
        GpuStatus,
        OfficeStatus,
        Project,
        ScanErrorEntry,
        ScanErrorReport,
        ScanEvent,
        ScanEventType,
        ScannedFolder,
        ScanOptions,
        ScanResult,
        ScanRunReport,
        TaxonomyManifest,
    )
    from doc_organize.core.progress import CancelToken, ProgressEvent
    from doc_organize.dedup.deduplication import DeduplicationManager
    from doc_organize.projects.layout import ProjectLayout
    from doc_organize.projects.project_history_cleaner import ProjectHistoryCleaner
    from doc_organize.projects.project_registry import ProjectRegistry
    from doc_organize.projects.scanned_folders_store import ScannedFoldersStore
    from doc_organize.scan.scan_command import DeduplicationSummary, ScanCommand, ScanSummary
    from doc_organize.scanner.document_scanner import DocumentScanner
    from doc_organize.utils.av_detector import detect_av_status
    from doc_organize.utils.gpu_detector import detect_gpu_status
    from doc_organize.utils.office_detector import detect_office_status
    from doc_organize.validators.folder_validator import FolderValidator
    from doc_organize.validators.project_validator import ProjectValidator
