"""Organización documental por dominios y contextos."""

from doc_organize.context.axis_rules import AxisRuleScorer
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_history import ContextHistoryPolicy, diff_contexts, list_context_builds
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier
from doc_organize.context.reorganizer import Reorganizer, resolve_organized_paths
from doc_organize.context.site_generator import SiteGenerator, SiteResult
from doc_organize.context.taxonomy_front_matter import inspect_taxonomy_front_matter, migrate_manifest_v1
from doc_organize.context.taxonomy_manifest import load_taxonomy_manifest, render_taxonomy_manifest_markdown, save_taxonomy_manifest
from doc_organize.context.taxonomy_manifest_sampler import select_document_sample
from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry
from doc_organize.context.taxonomy_templates import (
    list_builtin_templates,
    load_builtin_template,
    parse_taxonomy_template,
    render_taxonomy_template,
)

__all__ = [
    "AxisRuleScorer",
    "ContextBuilder",
    "ContextHistoryPolicy",
    "ContextRegistry",
    "DomainClassifier",
    "MaterialTypeClassifier",
    "Reorganizer",
    "SiteGenerator",
    "SiteResult",
    "TaxonomyTemplateRegistry",
    "diff_contexts",
    "inspect_taxonomy_front_matter",
    "list_builtin_templates",
    "list_context_builds",
    "load_builtin_template",
    "load_taxonomy_manifest",
    "migrate_manifest_v1",
    "parse_taxonomy_template",
    "render_taxonomy_manifest_markdown",
    "render_taxonomy_template",
    "resolve_organized_paths",
    "save_taxonomy_manifest",
    "select_document_sample",
]
