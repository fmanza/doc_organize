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
    "resolve_organized_paths": "doc_organize.context.reorganizer",  # L-8d
    "SiteGenerator": "doc_organize.context.site_generator",
    "SiteResult": "doc_organize.context.site_generator",
    "TaxonomyTemplateRegistry": "doc_organize.context.taxonomy_template_registry",
    # Plantillas de taxonomía como texto, sin carpeta de usuario (L-8c)
    "parse_taxonomy_template": "doc_organize.context.taxonomy_templates",
    "render_taxonomy_template": "doc_organize.context.taxonomy_templates",
    "list_builtin_templates": "doc_organize.context.taxonomy_templates",
    "load_builtin_template": "doc_organize.context.taxonomy_templates",
    # Manifiesto 2.0 por ejes (A1)
    "migrate_manifest_v1": "doc_organize.context.taxonomy_front_matter",
    "check_context_freshness": "doc_organize.context.freshness",
    # Evaluación contra una referencia (2.0.0, G3)
    "evaluate_classification": "doc_organize.context.evaluation",
    "load_gold_xlsx": "doc_organize.context.evaluation",
    "GoldStandard": "doc_organize.context.evaluation",
    "GoldLabel": "doc_organize.context.evaluation",
    "EvaluationReport": "doc_organize.context.evaluation",
    "AxisEvaluation": "doc_organize.context.evaluation",
    "dry_run_classify": "doc_organize.context.dry_run",
    "DryRunResult": "doc_organize.context.dry_run",
    # Decisiones de personas (2.0.0, F6)
    "ClassificationDecision": "doc_organize.core.models",
    "ClassificationDecisionStore": "doc_organize.context.decisions",
    "DecisionIssue": "doc_organize.core.models",
    "gold_from_decisions": "doc_organize.context.decisions",
    # Cola de revisión (2.0.0, F6)
    "review_queue": "doc_organize.context.review_queue",
    "ReviewItem": "doc_organize.context.review_queue",
    # Versiones de un documento (2.0.0, F5)
    "detect_document_versions": "doc_organize.context.versions",
    "DocumentVersionGroup": "doc_organize.core.models",
    # Diagnóstico del entorno (2.0.0, F2)
    "check_environment": "doc_organize.diagnostics",
    # Cliente único de IA (2.0.0, G1)
    "LlmClient": "doc_organize.ai.llm_client",
    # Agentes (2.0.0, G5)
    "AgentRunner": "doc_organize.ai.agents",
    "AgentTool": "doc_organize.ai.agents",
    "AgentLimits": "doc_organize.ai.agents",
    "AgentCancellation": "doc_organize.ai.agents",
    "AgentRun": "doc_organize.ai.agents",
    "PromptRegistry": "doc_organize.ai.prompts",
    "settings_from_env": "doc_organize.ai.settings",
    "AiResultCache": "doc_organize.ai.cache",
    "prune_ai_cache": "doc_organize.ai.cache",
    "AiSettings": "doc_organize.core.models",
    "TaskSettings": "doc_organize.core.models",
    "AiEndpoint": "doc_organize.diagnostics",
    "EnvironmentCheck": "doc_organize.core.models",
    "EnvironmentReport": "doc_organize.core.models",
    "inspect_taxonomy_front_matter": "doc_organize.context.taxonomy_front_matter",
    "ProjectRegistry": "doc_organize.projects.project_registry",
    "ProjectLayout": "doc_organize.projects.layout",
    # Rutas de salida de un documento (sin Docling, G20/G23)
    "resolve_output_paths": "doc_organize.projects.layout",
    "resolve_images_dir": "doc_organize.projects.layout",
    "relative_source_path": "doc_organize.projects.layout",
    # Carpeta reorganizada del contexto (L-8b)
    "RESERVED_OUTPUT_FOLDER_NAMES": "doc_organize.projects.layout",
    "validate_output_folder_name": "doc_organize.projects.layout",
    "ProjectHistoryCleaner": "doc_organize.projects.project_history_cleaner",
    "ScannedFoldersStore": "doc_organize.projects.scanned_folders_store",
    "FolderValidator": "doc_organize.validators.folder_validator",
    # Exportación (L-7): ZIP en streaming, vista previa y Excel (extra `export` para el Excel)
    "ExportStats": "doc_organize.export.zip_export",
    "preview_project_zip": "doc_organize.export.zip_export",
    "write_project_zip": "doc_organize.export.zip_export",
    "write_cache_xlsx": "doc_organize.export.xlsx_export",
    "write_scan_errors_xlsx": "doc_organize.export.xlsx_export",
    "write_context_documents_xlsx": "doc_organize.export.xlsx_export",
    "load_cache_entries": "doc_organize.export.sources",
    "load_scan_error_history": "doc_organize.export.sources",
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
    "DedupMode": "doc_organize.core.models",
    "DeduplicationReport": "doc_organize.core.models",
    "CacheEntry": "doc_organize.core.models",
    "ConversionStatus": "doc_organize.core.models",
    "DocumentStatus": "doc_organize.core.models",
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
    "TaxonomyAxis": "doc_organize.core.models",
    "TaxonomyEntry": "doc_organize.core.models",
    "TaxonomyFrontMatterReport": "doc_organize.core.models",
    "FreshnessReport": "doc_organize.core.models",
    "AxisValue": "doc_organize.core.models",
    "DocumentClassification": "doc_organize.core.models",
    "DocumentCredentialFindings": "doc_organize.core.models",
    # Credenciales (1.7.0)
    "redact_credentials": "doc_organize.security.credentials",
    "scan_credentials": "doc_organize.security.credentials",
    "RedactionResult": "doc_organize.security.credentials",
    "CredentialFinding": "doc_organize.security.credentials",
    # Errores
    "DocOrganizeError": "doc_organize.core.exceptions",
    "OperationCancelledError": "doc_organize.core.exceptions",
    "InvalidPathError": "doc_organize.core.exceptions",
    "MissingDependencyError": "doc_organize.core.exceptions",
    "ConversionError": "doc_organize.core.exceptions",
    "CacheError": "doc_organize.core.exceptions",
    "CacheNotFoundError": "doc_organize.core.exceptions",
    "ModelsNotAvailableError": "doc_organize.core.exceptions",
    "ProjectError": "doc_organize.core.exceptions",
    "ProjectNotFoundError": "doc_organize.core.exceptions",
    "ContextError": "doc_organize.core.exceptions",
    "SiteBuildError": "doc_organize.core.exceptions",
}

__all__ = ["__version__", *sorted(_EXPORTS)]  # noqa: PLE0604 - las claves de _EXPORTS son cadenas


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
    from doc_organize.context.decisions import ClassificationDecisionStore, gold_from_decisions
    from doc_organize.context.dry_run import DryRunResult, dry_run_classify
    from doc_organize.context.evaluation import (
        AxisEvaluation,
        EvaluationReport,
        GoldLabel,
        GoldStandard,
        evaluate_classification,
        load_gold_xlsx,
    )
    from doc_organize.context.freshness import check_context_freshness
    from doc_organize.context.reorganizer import Reorganizer, resolve_organized_paths
    from doc_organize.context.review_queue import ReviewItem, review_queue
    from doc_organize.context.site_generator import SiteGenerator, SiteResult
    from doc_organize.context.taxonomy_front_matter import inspect_taxonomy_front_matter, migrate_manifest_v1
    from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry
    from doc_organize.context.taxonomy_templates import (
        list_builtin_templates,
        load_builtin_template,
        parse_taxonomy_template,
        render_taxonomy_template,
    )
    from doc_organize.context.versions import detect_document_versions
    from doc_organize.converter.converter import DocumentConverter
    from doc_organize.converter.ocr_scheduler import OCRScheduler
    from doc_organize.core.exceptions import (
        CacheError,
        CacheNotFoundError,
        ContextError,
        ConversionError,
        DocOrganizeError,
        InvalidPathError,
        MissingDependencyError,
        ModelsNotAvailableError,
        OperationCancelledError,
        ProjectError,
        ProjectNotFoundError,
        SiteBuildError,
    )
    from doc_organize.core.models import (
        AiSettings,
        AvStatus,
        AxisValue,
        CacheEntry,
        ClassificationDecision,
        Context,
        ContextBuildEvent,
        ContextBuildEventType,
        ContextDeleteEvent,
        ContextDeleteEventType,
        ConversionResult,
        ConversionStatus,
        DecisionIssue,
        DedupEvent,
        DedupEventType,
        DeduplicationReport,
        DedupMode,
        DocumentClassification,
        DocumentCredentialFindings,
        DocumentMetadata,
        DocumentStatus,
        DocumentVersionGroup,
        DuplicateGroup,
        DuplicateReason,
        EnvironmentCheck,
        EnvironmentReport,
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
        TaskSettings,
        TaxonomyAxis,
        TaxonomyEntry,
        TaxonomyFrontMatterReport,
        TaxonomyManifest,
    )
    from doc_organize.core.progress import CancelToken, ProgressEvent
    from doc_organize.dedup.deduplication import DeduplicationManager
    from doc_organize.diagnostics import AiEndpoint, check_environment
    from doc_organize.export.sources import load_cache_entries, load_scan_error_history
    from doc_organize.export.xlsx_export import write_cache_xlsx, write_context_documents_xlsx, write_scan_errors_xlsx
    from doc_organize.export.zip_export import ExportStats, preview_project_zip, write_project_zip
    from doc_organize.projects.layout import (
        RESERVED_OUTPUT_FOLDER_NAMES,
        ProjectLayout,
        relative_source_path,
        resolve_images_dir,
        resolve_output_paths,
        validate_output_folder_name,
    )
    from doc_organize.projects.project_history_cleaner import ProjectHistoryCleaner
    from doc_organize.projects.project_registry import ProjectRegistry
    from doc_organize.projects.scanned_folders_store import ScannedFoldersStore
    from doc_organize.scan.scan_command import DeduplicationSummary, ScanCommand, ScanSummary
    from doc_organize.scanner.document_scanner import DocumentScanner
    from doc_organize.security.credentials import CredentialFinding, RedactionResult, redact_credentials, scan_credentials
    from doc_organize.utils.av_detector import detect_av_status
    from doc_organize.utils.gpu_detector import detect_gpu_status
    from doc_organize.utils.office_detector import detect_office_status
    from doc_organize.validators.folder_validator import FolderValidator
    from doc_organize.validators.project_validator import ProjectValidator
