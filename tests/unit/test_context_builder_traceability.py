"""Trazabilidad de la clasificación (1.5.0): qué propusieron las reglas, qué dijo la IA y con qué modelo y versión."""

import json

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_organize import __version__
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.core.models import (
    Context,
    ConversionResult,
    DocumentEnrichmentResult,
    DomainClassificationResult,
    DomainDocument,
    Project,
    TaxonomyCatalogEntry,
    TaxonomyClassificationResult,
    TaxonomyManifest,
)


def _document(tmp_path: Path, folder: str, name: str, text: str) -> ConversionResult:
    source = tmp_path / folder / name
    source.parent.mkdir(exist_ok=True)
    json_path = tmp_path / f"{source.stem}.json"
    json_path.write_text(json.dumps({"title": source.stem, "chunks": [{"text": text}]}), encoding="utf-8")
    markdown_path = tmp_path / f"{source.stem}.md"
    markdown_path.write_text(text, encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown_path), json_path=str(json_path), success=True)


def _by_name(context: Context) -> dict[str, DomainDocument]:
    return {Path(document.source_path).name: document for domain in context.domains for document in domain.documents}


class _DomainAI:
    config = SimpleNamespace(model="modelo-dominios")

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.calls = 0

    async def classify(self, *, chunks_text: str, title: str | None, candidate_domains: list[str]) -> DomainClassificationResult:
        self.calls += 1
        return DomainClassificationResult(domain=self.domain, confidence=0.9, reasoning="  Habla de\nauditorías de calidad ")


class _TaxonomyAI:
    config = SimpleNamespace(model="modelo-taxonomia")

    def __init__(self, domain: str = "calidad") -> None:
        self.domain = domain

    async def classify(
        self, *, chunks_text: str, title: str | None, candidate_domains: list[str], candidate_material_types: list[str]
    ) -> TaxonomyClassificationResult:
        return TaxonomyClassificationResult(
            domain=self.domain,
            domain_confidence=0.7,
            material_type="normativa",
            material_type_confidence=0.6,
            reasoning="Es un procedimiento de calidad",
        )


class _Enricher:
    config = SimpleNamespace(model="modelo-descripciones")

    async def enrich(self, *, chunks_text: str, title: str | None) -> DocumentEnrichmentResult:
        return DocumentEnrichmentResult(description="Resumen", keywords=["ia"])


async def _build(tmp_path: Path, documents: list[ConversionResult], **kwargs: object) -> Context:
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    return await ContextBuilder(ContextRegistry()).build(project, documents, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rules_and_ai_proposals_are_both_recorded(tmp_path: Path) -> None:
    documents = [
        _document(tmp_path, "varios", "manual.pdf", "Manual del sistema de gestión de calidad."),  # 2/2 palabras, sin distinguir tildes
        _document(tmp_path, "varios", "acta.pdf", "Acta de la reunión sobre calidad del servicio."),  # 1/2: 0,5 < 0,6
    ]
    client = _DomainAI("gestion-calidad")

    context = await _build(
        tmp_path,
        documents,
        candidate_domains=["gestion-calidad"],
        threshold=0.6,
        ai_classification_enabled=True,
        ai_classification_client=client,
    )

    docs = _by_name(context)
    by_rules = docs["manual.pdf"]
    assert (by_rules.classified_by, by_rules.rules_domain, by_rules.rules_confidence) == ("rules", "gestion-calidad", 1.0)
    assert (by_rules.ai_confidence, by_rules.ai_reasoning) == (None, None)

    by_ai = docs["acta.pdf"]
    assert (by_ai.classified_by, by_ai.confidence) == ("ai", 0.9)
    assert (by_ai.rules_domain, by_ai.rules_confidence) == ("gestion-calidad", 0.5)  # lo que las reglas dejaron por debajo
    assert (by_ai.ai_domain, by_ai.ai_confidence, by_ai.ai_reasoning) == ("gestion-calidad", 0.9, "Habla de auditorías de calidad")

    assert client.calls == 1
    assert context.ai_classification_model == "modelo-dominios"
    assert context.built_with_version == __version__


@pytest.mark.asyncio
async def test_manifest_mode_records_both_axes(tmp_path: Path) -> None:
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad")],
        material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento"), TaxonomyCatalogEntry(slug="normativa", name="Normativa")],
    )
    documents = [_document(tmp_path, "varios", "pr07.pdf", "Este procedimiento describe las auditorías internas.")]

    context = await _build(
        tmp_path, documents, taxonomy_manifest=manifest, ai_classification_enabled=True, taxonomy_classification_client=_TaxonomyAI()
    )

    (document,) = _by_name(context).values()
    assert (document.classified_by, document.confidence) == ("ai", 0.7)
    assert (document.rules_domain, document.rules_confidence) == (None, 0.0)  # las reglas no encontraron dominio
    assert (document.ai_domain, document.ai_confidence, document.ai_reasoning) == ("calidad", 0.7, "Es un procedimiento de calidad")
    # El tipo de material lo decidieron las reglas: la propuesta de la IA para ese eje no se aplica.
    assert (document.material_type, document.material_type_confidence) == ("procedimiento", 1.0)
    assert context.ai_classification_model == "modelo-taxonomia"


@pytest.mark.asyncio
async def test_manifest_mode_keeps_the_ai_domain_proposal_it_did_not_apply(tmp_path: Path) -> None:
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad"), TaxonomyCatalogEntry(slug="auditoria", name="Auditoría")],
        material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento"), TaxonomyCatalogEntry(slug="normativa", name="Normativa")],
    )
    documents = [_document(tmp_path, "varios", "manual.pdf", "Manual de calidad del laboratorio.")]  # dominio sí, tipo no

    context = await _build(
        tmp_path, documents, taxonomy_manifest=manifest, ai_classification_enabled=True, taxonomy_classification_client=_TaxonomyAI("auditoria")
    )

    (domain,) = context.domains
    (document,) = domain.documents
    assert domain.slug == "calidad"  # el dominio lo decidieron las reglas
    assert (document.rules_domain, document.confidence) == ("calidad", 1.0)
    assert (document.ai_domain, document.ai_confidence) == ("auditoria", 0.7)  # propuesta de la IA, no aplicada
    assert (document.classified_by, document.material_type, document.material_type_confidence) == ("ai", "normativa", 0.6)


@pytest.mark.asyncio
async def test_models_are_recorded_only_when_the_ai_phase_sent_something(tmp_path: Path) -> None:
    documents = [_document(tmp_path, "Calidad", "manual.pdf", "Manual de calidad.")]

    context = await _build(
        tmp_path,
        documents,
        ai_classification_enabled=True,
        ai_classification_client=_DomainAI("calidad"),  # la Sub-fase A lo clasifica: no hay nada que enviar
        ai_enrichment_enabled=True,
        ai_enrichment_client=_Enricher(),
    )

    assert context.ai_classification_model is None
    assert context.ai_enrichment_model == "modelo-descripciones"


@pytest.mark.asyncio
async def test_traceability_survives_save_and_load(tmp_path: Path) -> None:
    documents = [_document(tmp_path, "varios", "acta.pdf", "Acta sobre calidad.")]
    context = await _build(
        tmp_path,
        documents,
        candidate_domains=["gestion-calidad"],
        threshold=0.6,
        ai_classification_enabled=True,
        ai_classification_client=_DomainAI("gestion-calidad"),
    )

    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    reloaded = await ContextRegistry().load_context(project)

    assert _by_name(reloaded)["acta.pdf"].model_dump() == _by_name(context)["acta.pdf"].model_dump()
    assert (reloaded.built_with_version, reloaded.ai_classification_model) == (__version__, "modelo-dominios")


def test_contexts_from_before_1_5_still_load() -> None:
    old = {"source_path": "/a.pdf", "markdown_path": "/a.md", "json_path": "/a.json", "title": "a", "document_type": "pdf", "confidence": 0.8}
    document = DomainDocument.model_validate(old)
    assert (document.rules_domain, document.rules_confidence, document.ai_confidence, document.ai_reasoning) == (None, None, None, None)
