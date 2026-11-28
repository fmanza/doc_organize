"""`ai_scope="all"` (2.7.0, P3): la IA clasifica todos los documentos en los ejes organizadores y sustituye lo que
asignaron las reglas, con su propuesta guardada por eje y las sustituciones contadas. Lo decidido por personas no se
pregunta; la cola no se llena de discrepancias con las reglas (PLAN C2, C3)."""

import json

from datetime import UTC, datetime
from typing import Any

import pytest

from doc_organize import ClassificationDecision, ContextBuilder, review_queue
from doc_organize.core.models import AiStats, ConversionResult, DomainDocument, Project, TaxonomyAxis, TaxonomyEntry
from tests.unit.fake_llm import FakeRequest, fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

TEXT = "Este manual describe el sistema de gestión de la calidad conforme a la norma ISO 9001 de la organización."


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, stem: str, title: str, text: str = TEXT) -> ConversionResult:
    folder = tmp_path / "entrada" / "Calidad"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(title, encoding="utf-8")
    return ConversionResult(
        source_path=str(folder / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md"),
        json_path=str(json_path),
        success=True,
        source_sha256="sha-1",
    )


def _manifest():
    domains = [TaxonomyEntry(slug="calidad", name="Calidad", keywords=["calidad"]), TaxonomyEntry(slug="seguridad", name="Seguridad")]
    types = [TaxonomyEntry(slug="manual", name="Manual", keywords=["manual"]), TaxonomyEntry(slug="politica", name="Política")]
    topics = TaxonomyAxis(key="topics", name="Temas", multiple=True, rules=False, entries=[TaxonomyEntry(slug="iso-9001", name="ISO 9001")])
    return two_axis_manifest(domains, types, extra_axes=[topics])


def _choice(slug: str, confidence: float = 0.9, evidence: str | None = "sistema de gestión") -> list[dict[str, Any]]:
    return [{"value": slug, "confidence": confidence, "evidence": evidence}]


async def _build(tmp_path, documents, respond, **kwargs):
    llm = fake_client(classify=respond)
    kwargs.setdefault("taxonomy_manifest", _manifest())
    kwargs.setdefault("ai_cache", False)
    context = await ContextBuilder().build(_project(tmp_path), documents, llm=llm, scan_roots=[str(tmp_path / "entrada")], **kwargs)
    by_path = {document.source_path: (domain.slug, document) for domain in context.domains for document in domain.documents}
    return context, by_path, llm


def _seguridad_politica(request: FakeRequest) -> dict:
    return {"domains": _choice("seguridad"), "material_types": _choice("politica")}


@pytest.mark.asyncio
async def test_all_replaces_the_rules_and_keeps_their_proposal_per_axis(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")

    context, by_path, llm = await _build(tmp_path, [document], _seguridad_politica, ai_scope="all")

    [request] = llm.proxy.requests
    assert request.axes == ["domains", "material_types"]  # los que solo etiquetan no se piden (lo medido en F0)
    domain_slug, result = by_path[document.source_path]
    assert domain_slug == "seguridad" and result.material_type == "politica"
    assert [(value.slug, value.classified_by) for value in result.classification.axes["domains"]] == [("seguridad", "ai")]
    assert [(value.slug, value.classified_by) for value in result.classification.axes["material_types"]] == [("politica", "ai")]
    assert (result.rules_domain, result.rules_material_type) == ("calidad", "manual")
    assert result.rules_confidence is not None and result.rules_material_type_confidence is not None
    assert result.classified_by == "ai"
    assert context.ai_stats.scope == "all"
    assert (context.ai_stats.classification.assigned, context.ai_stats.classification.replaced) == (1, 2)
    assert [domain.slug for domain in context.domains] == ["seguridad"]  # sin cubo vacío de «calidad»


@pytest.mark.asyncio
async def test_agreeing_with_the_rules_is_not_a_replacement(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")

    context, by_path, _ = await _build(
        tmp_path, [document], lambda request: {"domains": _choice("calidad"), "material_types": _choice("politica")}, ai_scope="all"
    )

    _, result = by_path[document.source_path]
    assert result.classification.axes["domains"][0].classified_by == "ai"
    assert context.ai_stats.classification.replaced == 1  # solo el tipo


@pytest.mark.asyncio
async def test_filling_what_the_rules_left_empty_is_not_a_replacement(tmp_path) -> None:
    document = _document(tmp_path, "nada", "Documento", text="Texto sin pistas sobre su contenido, solo relleno de prueba suficiente.")

    context, by_path, _ = await _build(tmp_path, [document], _seguridad_politica, ai_scope="all")

    domain_slug, result = by_path[document.source_path]
    assert domain_slug == "seguridad" and result.rules_material_type is None
    assert context.ai_stats.classification.replaced == 0


@pytest.mark.asyncio
async def test_all_never_asks_or_replaces_what_a_person_decided(tmp_path) -> None:
    decided = _document(tmp_path, "decidido", "Manual de calidad")
    decision = ClassificationDecision(
        document_key="Calidad/decidido.pdf", action="set_axis", axes={"domains": ["calidad"]}, source_sha256="sha-1", id="d-1"
    )

    context, by_path, llm = await _build(tmp_path, [decided], _seguridad_politica, ai_scope="all", decisions=[decision])

    [request] = llm.proxy.requests
    assert request.axes == ["material_types"]
    domain_slug, result = by_path[decided.source_path]
    assert domain_slug == "calidad" and result.classification.axes["domains"][0].classified_by == "human"
    assert result.material_type == "politica"
    assert context.ai_stats.classification.replaced == 1


@pytest.mark.asyncio
async def test_all_does_not_flood_the_review_queue_with_disagreements(tmp_path) -> None:
    documents = [_document(tmp_path, f"manual{i}", "Manual de calidad") for i in range(3)]

    context, _, _ = await _build(tmp_path, documents, _seguridad_politica, ai_scope="all")

    assert context.ai_stats.classification.replaced == 6
    assert [item for item in review_queue(context, roots=[str(tmp_path / "entrada")]) if item.reason == "rules_ai_disagreement"] == []


@pytest.mark.asyncio
async def test_documents_left_out_by_the_budget_keep_the_rules(tmp_path) -> None:
    documents = [_document(tmp_path, f"manual{i}", "Manual de calidad") for i in range(2)]

    context, by_path, _ = await _build(tmp_path, documents, _seguridad_politica, ai_scope="all", ai_max_documents=1)

    assert sorted(slug for slug, _ in by_path.values()) == ["calidad", "seguridad"]
    assert context.ai_stats.classification.stopped == "budget"


@pytest.mark.asyncio
async def test_rebuilding_with_all_and_no_changes_sends_nothing(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")
    await _build(tmp_path, [document], _seguridad_politica, ai_scope="all", ai_cache=True)

    context, by_path, llm = await _build(tmp_path, [document], _seguridad_politica, ai_scope="all", ai_cache=True)

    assert llm.proxy.requests == []
    assert by_path[document.source_path][0] == "seguridad"
    assert (context.ai_stats.classification.cached, context.ai_stats.classification.replaced) == (1, 2)


@pytest.mark.asyncio
async def test_all_without_a_manifest_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="manifiesto"):
        await ContextBuilder().build(_project(tmp_path), [], llm=fake_client(), ai_scope="all")


@pytest.mark.asyncio
async def test_other_scopes_still_never_replace(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")

    context, by_path, llm = await _build(tmp_path, [document], _seguridad_politica, ai_scope="unclassified")

    assert llm.proxy.requests == []
    _, result = by_path[document.source_path]
    assert (result.material_type, result.rules_material_type) == ("manual", "manual")
    assert context.ai_stats.classification.replaced == 0


def test_contexts_from_2_6_load_without_the_new_fields() -> None:
    document = DomainDocument.model_validate(
        {"source_path": "a.pdf", "markdown_path": "a.md", "json_path": "a.json", "title": "A", "document_type": "pdf", "confidence": 0.7}
    )
    stats = AiStats.model_validate({"scope": "unclassified", "classification": {"sent": 3, "assigned": 2}})

    assert (document.rules_material_type, document.rules_material_type_confidence) == (None, None)
    assert stats.classification.replaced == 0
