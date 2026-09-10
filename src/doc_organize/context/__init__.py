"""Organización documental por dominios y contextos."""

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier
from doc_organize.context.mkdocs_generator import MkDocsGenerator
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.taxonomy_manifest import load_taxonomy_manifest, render_taxonomy_manifest_markdown
from doc_organize.context.taxonomy_manifest_sampler import select_document_sample
from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry

__all__ = [
    "ContextBuilder",
    "ContextRegistry",
    "DomainClassifier",
    "MaterialTypeClassifier",
    "MkDocsGenerator",
    "Reorganizer",
    "TaxonomyTemplateRegistry",
    "load_taxonomy_manifest",
    "render_taxonomy_manifest_markdown",
    "select_document_sample",
]
