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
    # Duplicados por contenido (2.2.0)
    "ContentDocument": "doc_organize.dedup.content",
    "ContentDuplicateFinder": "doc_organize.dedup.content",
    "ContentDuplicateReport": "doc_organize.dedup.content",
    "exclude_from_context": "doc_organize.dedup.content",
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
    "DocumentChange": "doc_organize.context.dry_run",
    "document_keys": "doc_organize.context.evaluation",
    "common_root": "doc_organize.context.evaluation",
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
    "embedding_index_info": "doc_organize.ai.embeddings",
    "clear_embedding_index": "doc_organize.ai.embeddings",
    "DocumentVersionGroup": "doc_organize.core.models",
    # Diagnóstico del entorno (2.0.0, F2)
    "check_environment": "doc_organize.diagnostics",
    # Cliente único de IA (2.0.0, G1)
    "LlmClient": "doc_organize.ai.llm_client",
    # Agentes (2.0.0, G5)
    "AgentRunner": "doc_organize.ai.agents",
    "AgentTool": "doc_organize.ai.agents",
    "AgentLimits": "doc_organize.ai.agents",
    "AgentRun": "doc_organize.ai.agents",
    "TaxonomyDesignAgent": "doc_organize.context.taxonomy_agent",
    "TaxonomyDesignProposal": "doc_organize.context.taxonomy_agent",
    "check_taxonomy_rules": "doc_organize.context.taxonomy_check",
    "RulesCorpus": "doc_organize.context.taxonomy_check",
    "TaxonomyRulesReport": "doc_organize.context.taxonomy_check",
    "ReviewAgent": "doc_organize.context.review_agent",
    "ReviewProposal": "doc_organize.context.review_agent",
    "ReviewResult": "doc_organize.context.review_agent",
    "audit_taxonomy": "doc_organize.context.review_agent",
    "TaxonomyAudit": "doc_organize.context.review_agent",
    "PromptRegistry": "doc_organize.ai.prompts",
    "settings_from_env": "doc_organize.ai.settings",
    "AiResultCache": "doc_organize.ai.cache",
    "prune_ai_cache": "doc_organize.ai.cache",
    "AiSettings": "doc_organize.core.models",
    "TaskSettings": "doc_organize.core.models",
    "default_model_alias": "doc_organize.core.models",
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
    "write_ai_context_bundle": "doc_organize.export.ai_bundle",
    "render_llms_txt": "doc_organize.context.llms_txt",
    "AiBundleStats": "doc_organize.export.ai_bundle",
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
    # Tipos que devuelve la API pública y que no estaban exportados (2.3.0)
    "VersionGroup": "doc_organize.context.versions",
    "VersionMember": "doc_organize.context.versions",
    "AgentStep": "doc_organize.ai.agents",
    "AgentToolCall": "doc_organize.ai.agents",
    "AxisRulesReport": "doc_organize.context.taxonomy_check",
    "NearMiss": "doc_organize.context.taxonomy_check",
    "AuditFinding": "doc_organize.context.review_agent",
    "LabelConfusion": "doc_organize.context.evaluation",
    "OfflineIssue": "doc_organize.context.offline_site",
    "EmbeddingIndexInfo": "doc_organize.ai.embeddings",
    "LlmResult": "doc_organize.ai.llm_client",
    "legacy_variables": "doc_organize.ai.settings",
    "REDACTED": "doc_organize.security.credentials",
    # Lo que ya usaba doc_organize_web desde submódulos (2.4.0): excepciones, modelos, funciones y constantes
    "AiError": "doc_organize.core.exceptions",
    "AiAuthError": "doc_organize.core.exceptions",
    "AiConnectionError": "doc_organize.core.exceptions",
    "AiConfigurationError": "doc_organize.core.exceptions",
    "UsageSourceError": "doc_organize.core.exceptions",
    "UsageSourceAuthError": "doc_organize.core.exceptions",
    "UsageSourceConnectionError": "doc_organize.core.exceptions",
    "ContextNotFoundError": "doc_organize.core.exceptions",
    "TaxonomyManifestError": "doc_organize.core.exceptions",
    "TaxonomyTemplateError": "doc_organize.core.exceptions",
    "ContextBuildRecord": "doc_organize.core.models",
    "ContextChange": "doc_organize.core.models",
    "UnclassifiedDocument": "doc_organize.core.models",
    "LiteLLMUsageConfig": "doc_organize.core.models",
    "DocumentProperties": "doc_organize.context.document_properties",
    "read_document_properties": "doc_organize.context.document_properties",
    "LiteLLMUsageClient": "doc_organize.ai.litellm_usage_client",
    "draft_taxonomy": "doc_organize.ai.services",
    "render_prompt_preview": "doc_organize.ai.services",
    "compose_profile": "doc_organize.context.project_profile",
    "compose_profile_text": "doc_organize.context.project_profile",
    "parse_profile": "doc_organize.context.project_profile",
    "PROJECT_PROFILE_FILE": "doc_organize.context.project_profile",
    "render_taxonomy_manifest_markdown": "doc_organize.context.taxonomy_manifest",
    "save_taxonomy_manifest": "doc_organize.context.taxonomy_manifest",
    "select_document_sample": "doc_organize.context.taxonomy_manifest_sampler",
    "load_context_history": "doc_organize.export.sources",
    "write_context_history_xlsx": "doc_organize.export.xlsx_export",
    "DECISIONS_FILE": "doc_organize.context.decisions",
    "DEFAULT_REVIEW_LIMITS": "doc_organize.context.review_agent",
    "DEFAULT_DESIGN_LIMITS": "doc_organize.context.taxonomy_agent",
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
    "neutralize_untrusted_markdown": "doc_organize.security.untrusted_markdown",
    "NeutralizeResult": "doc_organize.security.untrusted_markdown",
    "check_site_offline": "doc_organize.context.offline_site",
    "OfflineSiteReport": "doc_organize.context.offline_site",
    "write_site_zip": "doc_organize.context.offline_site",
    "SiteZipResult": "doc_organize.context.offline_site",
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
    "OfflineSiteError": "doc_organize.core.exceptions",
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
    # Uno por nombre de _EXPORTS (lo comprueba tests/unit/test_public_api.py): sin esto, mypy y el IDE no ven el
    # tipo de lo que se importa bajo demanda.
    from doc_organize.ai.agents import AgentLimits, AgentRun, AgentRunner, AgentStep, AgentTool, AgentToolCall
    from doc_organize.ai.cache import AiResultCache, prune_ai_cache
    from doc_organize.ai.embeddings import EmbeddingIndexInfo, clear_embedding_index, embedding_index_info
    from doc_organize.ai.litellm_usage_client import LiteLLMUsageClient
    from doc_organize.ai.llm_client import LlmClient, LlmResult
    from doc_organize.ai.prompts import PromptRegistry
    from doc_organize.ai.services import draft_taxonomy, render_prompt_preview
    from doc_organize.ai.settings import legacy_variables, settings_from_env
    from doc_organize.cache.cache_manager import CacheManager
    from doc_organize.context.context_builder import ContextBuilder
    from doc_organize.context.context_registry import ContextRegistry
    from doc_organize.context.decisions import DECISIONS_FILE, ClassificationDecisionStore, gold_from_decisions
    from doc_organize.context.document_properties import DocumentProperties, read_document_properties
    from doc_organize.context.dry_run import DocumentChange, DryRunResult, dry_run_classify
    from doc_organize.context.evaluation import (
        AxisEvaluation,
        EvaluationReport,
        GoldLabel,
        GoldStandard,
        LabelConfusion,
        common_root,
        document_keys,
        evaluate_classification,
        load_gold_xlsx,
    )
    from doc_organize.context.freshness import check_context_freshness
    from doc_organize.context.llms_txt import render_llms_txt
    from doc_organize.context.offline_site import OfflineIssue, OfflineSiteReport, SiteZipResult, check_site_offline, write_site_zip
    from doc_organize.context.project_profile import PROJECT_PROFILE_FILE, compose_profile, compose_profile_text, parse_profile
    from doc_organize.context.reorganizer import Reorganizer, resolve_organized_paths
    from doc_organize.context.review_agent import (
        DEFAULT_REVIEW_LIMITS,
        AuditFinding,
        ReviewAgent,
        ReviewProposal,
        ReviewResult,
        TaxonomyAudit,
        audit_taxonomy,
    )
    from doc_organize.context.review_queue import ReviewItem, review_queue
    from doc_organize.context.site_generator import SiteGenerator, SiteResult
    from doc_organize.context.taxonomy_agent import DEFAULT_DESIGN_LIMITS, TaxonomyDesignAgent, TaxonomyDesignProposal
    from doc_organize.context.taxonomy_check import AxisRulesReport, NearMiss, RulesCorpus, TaxonomyRulesReport, check_taxonomy_rules
    from doc_organize.context.taxonomy_front_matter import inspect_taxonomy_front_matter, migrate_manifest_v1
    from doc_organize.context.taxonomy_manifest import render_taxonomy_manifest_markdown, save_taxonomy_manifest
    from doc_organize.context.taxonomy_manifest_sampler import select_document_sample
    from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry
    from doc_organize.context.taxonomy_templates import (
        list_builtin_templates,
        load_builtin_template,
        parse_taxonomy_template,
        render_taxonomy_template,
    )
    from doc_organize.context.versions import VersionGroup, VersionMember, detect_document_versions
    from doc_organize.converter.converter import DocumentConverter
    from doc_organize.converter.ocr_scheduler import OCRScheduler
    from doc_organize.core.exceptions import (
        AiAuthError,
        AiConfigurationError,
        AiConnectionError,
        AiError,
        CacheError,
        CacheNotFoundError,
        ContextError,
        ContextNotFoundError,
        ConversionError,
        DocOrganizeError,
        InvalidPathError,
        MissingDependencyError,
        ModelsNotAvailableError,
        OfflineSiteError,
        OperationCancelledError,
        ProjectError,
        ProjectNotFoundError,
        SiteBuildError,
        TaxonomyManifestError,
        TaxonomyTemplateError,
        UsageSourceAuthError,
        UsageSourceConnectionError,
        UsageSourceError,
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
        ContextBuildRecord,
        ContextChange,
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
        FreshnessReport,
        GpuStatus,
        LiteLLMUsageConfig,
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
        UnclassifiedDocument,
        default_model_alias,
    )
    from doc_organize.core.progress import CancelToken, ProgressEvent
    from doc_organize.dedup.content import ContentDocument, ContentDuplicateFinder, ContentDuplicateReport, exclude_from_context
    from doc_organize.dedup.deduplication import DeduplicationManager
    from doc_organize.diagnostics import AiEndpoint, check_environment
    from doc_organize.export.ai_bundle import AiBundleStats, write_ai_context_bundle
    from doc_organize.export.sources import load_cache_entries, load_context_history, load_scan_error_history
    from doc_organize.export.xlsx_export import write_cache_xlsx, write_context_documents_xlsx, write_context_history_xlsx, write_scan_errors_xlsx
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
    from doc_organize.security.credentials import REDACTED, CredentialFinding, RedactionResult, redact_credentials, scan_credentials
    from doc_organize.security.untrusted_markdown import NeutralizeResult, neutralize_untrusted_markdown
    from doc_organize.utils.av_detector import detect_av_status
    from doc_organize.utils.gpu_detector import detect_gpu_status
    from doc_organize.utils.office_detector import detect_office_status
    from doc_organize.validators.folder_validator import FolderValidator
    from doc_organize.validators.project_validator import ProjectValidator
