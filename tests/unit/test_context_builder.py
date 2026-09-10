"""Tests de ContextBuilder (orquesta DomainClassifier + ContextRegistry)."""

import json

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.core.exceptions import DomainClassificationError
from doc_organize.core.models import ConversionResult, DomainClassificationResult, Project


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _make_document(tmp_path, folder: str, stem: str, title: str) -> ConversionResult:
    source_dir = tmp_path / folder
    source_dir.mkdir(exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": []}), encoding="utf-8")
    return ConversionResult(
        source_path=str(source_dir / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md"),
        json_path=str(json_path),
        success=True,
    )


@pytest.mark.asyncio
async def test_build_persists_discovered_domains(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    builder = ContextBuilder()
    context = await builder.build(project, [document])

    assert len(context.domains) == 1
    assert context.domains[0].slug == "ciberseguridad"
    assert context.unclassified_documents == []

    reloaded = await builder.registry.load_context(project)
    assert reloaded.domains[0].slug == "ciberseguridad"


@pytest.mark.asyncio
async def test_build_uses_default_output_folder_name_when_not_given(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    context = await ContextBuilder().build(project, [document])

    assert context.output_folder_name == "organizado"


@pytest.mark.asyncio
async def test_build_uses_given_output_folder_name(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    context = await ContextBuilder().build(project, [document], output_folder_name="docs_publicados")

    assert context.output_folder_name == "docs_publicados"


@pytest.mark.asyncio
async def test_build_tracks_unclassified_documents_outside_catalog(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    builder = ContextBuilder()
    context = await builder.build(project, [document], candidate_domains=["calidad"])

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]


class _StubAIClient:
    """Doble de `DomainClassificationClient` para tests — mismo contrato (`async classify(...)`
    devolviendo `DomainClassificationResult`), sin `httpx` de por medio."""

    def __init__(self, domain: str | None, confidence: float = 0.8, error: bool = False) -> None:
        self.domain = domain
        self.confidence = confidence
        self.error = error
        self.calls: list[list[str]] = []

    async def classify(self, *, chunks_text: str, title: str | None, candidate_domains: list[str]) -> DomainClassificationResult:
        self.calls.append(candidate_domains)
        if self.error:
            raise DomainClassificationError("fallo simulado del proxy")
        return DomainClassificationResult(domain=self.domain, confidence=self.confidence, reasoning=None)


@pytest.mark.asyncio
async def test_ai_fallback_classifies_document_left_unclassified_by_rules(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain="calidad")
    builder = ContextBuilder()
    context = await builder.build(
        project,
        [document],
        candidate_domains=["calidad"],
        ai_classification_enabled=True,
        ai_classification_client=ai_client,
    )

    assert context.unclassified_documents == []
    assert context.domains[0].slug == "calidad"
    assert context.domains[0].documents[0].classified_by == "ai"
    assert ai_client.calls == [["calidad"]]  # catálogo predefinido, nunca inventado


@pytest.mark.asyncio
async def test_on_ai_progress_called_once_per_unclassified_document(tmp_path):
    project = _make_project(tmp_path)
    doc_a = _make_document(tmp_path, "varios", "a", "Receta A")
    doc_b = _make_document(tmp_path, "varios", "b", "Receta B")

    progress_calls: list[tuple[int, int, str]] = []

    async def on_progress(index: int, total: int, path: str) -> None:
        progress_calls.append((index, total, path))

    ai_client = _StubAIClient(domain="calidad")
    builder = ContextBuilder()
    await builder.build(
        project,
        [doc_a, doc_b],
        candidate_domains=["calidad"],
        ai_classification_enabled=True,
        ai_classification_client=ai_client,
        on_ai_progress=on_progress,
    )

    assert progress_calls == [(1, 2, doc_a.source_path), (2, 2, doc_b.source_path)]


@pytest.mark.asyncio
async def test_on_ai_progress_not_called_when_ai_disabled(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    progress_calls: list[tuple[int, int, str]] = []

    async def on_progress(index: int, total: int, path: str) -> None:
        progress_calls.append((index, total, path))

    await ContextBuilder().build(project, [document], candidate_domains=["calidad"], on_ai_progress=on_progress)

    assert progress_calls == []


@pytest.mark.asyncio
async def test_ai_fallback_never_invents_domain_when_ai_finds_no_match(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain=None)
    builder = ContextBuilder()
    context = await builder.build(
        project, [document], candidate_domains=["calidad"], ai_classification_enabled=True, ai_classification_client=ai_client
    )

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]


@pytest.mark.asyncio
async def test_ai_fallback_client_error_leaves_document_unclassified_without_crashing(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain="calidad", error=True)
    builder = ContextBuilder()
    context = await builder.build(
        project, [document], candidate_domains=["calidad"], ai_classification_enabled=True, ai_classification_client=ai_client
    )

    assert context.unclassified_documents == [document.source_path]


@pytest.mark.asyncio
async def test_ai_fallback_disabled_by_default_even_with_client_provided(tmp_path):
    """`ai_classification_enabled=False` (default) — opt-in explícito, el cliente no se usa."""
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain="calidad")
    builder = ContextBuilder()
    context = await builder.build(project, [document], candidate_domains=["calidad"], ai_classification_client=ai_client)

    assert context.unclassified_documents == [document.source_path]
    assert ai_client.calls == []


@pytest.mark.asyncio
async def test_ai_fallback_skips_when_no_catalog_available_at_all(tmp_path):
    """Sin `candidate_domains` y sin ningún dominio descubierto por la Sub-fase A
    (aquí, porque el `.json` es ilegible y por tanto tampoco hay `chunks_text` que
    ofrecerle a la IA), no hay catálogo del que elegir — la Sub-fase B ni siquiera
    llama al cliente, nunca inventa un dominio de la nada. Nota: en modo
    descubrimiento, un documento con `.json` legible SIEMPRE lo clasifica la
    Sub-fase A (score fijo 1.0 por carpeta) — el único caso realista en el que la
    Sub-fase A "falla" en ese modo es un artefacto no legible, que tampoco puede
    resolver la Sub-fase B al depender de la misma fuente (`00_REQUEST.md` §2.4).
    """
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "roto", "Roto")
    Path(document.json_path).unlink()

    ai_client = _StubAIClient(domain="lo-que-sea")
    builder = ContextBuilder()
    context = await builder.build(project, [document], ai_classification_enabled=True, ai_classification_client=ai_client)

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]
    assert ai_client.calls == []
