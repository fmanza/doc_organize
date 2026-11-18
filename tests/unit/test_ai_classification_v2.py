"""Clasificación con IA de 2.0 en una construcción (M5, G1.4 + G2): alcance `missing_axes`, la IA solo rellena ejes
vacíos, cita verificada (D10), umbral de los ejes que etiquetan, perfil y extracto en la petición."""

import json

from datetime import UTC, datetime
from typing import Any

import pytest

from doc_organize import ContextBuilder
from doc_organize.context.project_profile import PROJECT_PROFILE_FILE
from doc_organize.core.models import ConversionResult, Project, ProjectProfile, TaxonomyAxis, TaxonomyEntry
from tests.unit.fake_llm import FakeRequest, fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

TEXT = "Este manual describe el sistema de gestión de la calidad conforme a la norma ISO 9001 de la organización."


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, stem: str, title: str, text: str = TEXT, folder: str = "Area/Calidad/2024") -> ConversionResult:
    (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text, "headings": ["1. Objeto"]}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(title, encoding="utf-8")
    return ConversionResult(
        source_path=str(tmp_path / folder / f"{stem}.pdf"), markdown_path=str(tmp_path / f"{stem}.md"), json_path=str(json_path), success=True
    )


def _manifest(topics_threshold: float | None = None, profile: ProjectProfile | None = None):
    entries = [
        TaxonomyEntry(slug="calidad", name="Calidad", keywords=["calidad"]),
        TaxonomyEntry(slug="seguridad", name="Seguridad", keywords=["ciberseguridad"]),
    ]
    types = [TaxonomyEntry(slug="manual", name="Manual", keywords=["manual"]), TaxonomyEntry(slug="politica", name="Política", keywords=["política"])]
    topics = TaxonomyAxis(
        key="topics",
        name="Temas",
        multiple=True,
        rules=False,
        threshold=topics_threshold,
        entries=[
            TaxonomyEntry(slug="auditoria", name="Auditoría", description="Auditorías internas"),
            TaxonomyEntry(slug="iso-9001", name="ISO 9001"),
        ],
    )
    manifest = two_axis_manifest(entries, types, extra_axes=[topics])
    return manifest.model_copy(update={"profile": profile})


def _choice(slug: str, confidence: float, evidence: str | None = None) -> dict[str, Any]:
    return {"value": slug, "confidence": confidence, "evidence": evidence}


async def _build(tmp_path, documents, respond, **kwargs):
    llm = fake_client(classify=respond)
    kwargs.setdefault("taxonomy_manifest", _manifest())
    context = await ContextBuilder().build(_project(tmp_path), documents, llm=llm, ai_cache=False, **kwargs)
    by_path = {document.source_path: document for domain in context.domains for document in domain.documents}
    return context, by_path, llm


@pytest.mark.asyncio
async def test_unclassified_scope_leaves_empty_tag_axes_alone(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")

    _, by_path, llm = await _build(tmp_path, [document], lambda request: {"topics": "iso-9001"}, ai_scope="unclassified")

    assert llm.proxy.requests == []  # las reglas resolvieron los dos organizadores
    assert by_path[document.source_path].classification.slugs("topics") == []


@pytest.mark.asyncio
async def test_missing_axes_asks_only_for_the_empty_axes_and_never_replaces_the_rules(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")

    def respond(request: FakeRequest) -> dict:
        return {"topics": [_choice("iso-9001", 0.9, "conforme a la norma ISO 9001"), _choice("auditoria", 0.7, "sistema de gestión")]}

    context, by_path, llm = await _build(tmp_path, [document], respond, ai_scope="missing_axes")

    [request] = llm.proxy.requests
    assert request.axes == ["topics"]
    result = by_path[document.source_path]
    axes = result.classification.axes
    assert [(value.slug, value.classified_by) for value in axes["domains"]] == [("calidad", "rules")]
    assert [(value.slug, value.classified_by) for value in axes["material_types"]] == [("manual", "rules")]
    assert [(value.slug, value.confidence, value.classified_by, value.evidence_verified) for value in axes["topics"]] == [
        ("iso-9001", 0.9, "ai", True),
        ("auditoria", 0.7, "ai", True),
    ]
    assert result.classified_by == "ai"
    assert context.ai_stats is not None and context.ai_stats.scope == "missing_axes"


@pytest.mark.asyncio
async def test_missing_axes_skips_documents_whose_tag_axes_already_have_values(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")
    manifest = _manifest().model_copy()
    manifest.axes[2] = manifest.axes[2].model_copy(update={"rules": True, "entries": [TaxonomyEntry(slug="iso-9001", name="ISO 9001")]})

    _, by_path, llm = await _build(tmp_path, [document], lambda request: {"topics": "iso-9001"}, ai_scope="missing_axes", taxonomy_manifest=manifest)

    assert llm.proxy.requests == []
    assert by_path[document.source_path].classification.axes["topics"][0].classified_by == "rules"


@pytest.mark.asyncio
async def test_unverified_evidence_keeps_the_value_below_the_threshold(tmp_path) -> None:
    """D10: una cita que no está en lo enviado no basta para dar el eje por clasificado; el valor queda para revisarlo."""
    document = _document(tmp_path, "doc", "Documento", text="Texto sin pistas sobre su contenido, solo relleno de prueba suficiente.")

    def respond(request: FakeRequest) -> dict:
        return {
            "domains": [_choice("seguridad", 0.95, "política de seguridad de la información")],
            "material_types": [_choice("politica", 0.8, "solo relleno de prueba")],
        }

    _, by_path, _ = await _build(tmp_path, [document], respond, ai_scope="unclassified", threshold=0.6)

    result = by_path[document.source_path]
    [domain] = result.classification.axes["domains"]
    assert (domain.slug, domain.confidence, domain.evidence_verified) == ("seguridad", pytest.approx(0.59), False)
    assert domain.evidence == "política de seguridad de la información"
    [material] = result.classification.axes["material_types"]
    assert (material.slug, material.confidence, material.evidence_verified) == ("politica", 0.8, True)


@pytest.mark.asyncio
async def test_tag_axis_values_below_the_axis_threshold_are_dropped(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")

    def respond(request: FakeRequest) -> dict:
        return {"topics": [_choice("iso-9001", 0.9), _choice("auditoria", 0.4)]}

    _, by_path, _ = await _build(tmp_path, [document], respond, ai_scope="missing_axes", taxonomy_manifest=_manifest(topics_threshold=0.5))

    assert by_path[document.source_path].classification.slugs("topics") == ["iso-9001"]


@pytest.mark.asyncio
async def test_the_request_carries_the_catalog_the_profile_and_the_excerpt(tmp_path) -> None:
    (tmp_path / PROJECT_PROFILE_FILE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / PROJECT_PROFILE_FILE).write_text("## Glosario\n\n- SGC: sistema de gestión de la calidad\n", encoding="utf-8")
    document = _document(tmp_path, "manual", "Manual de calidad")
    manifest = _manifest(profile=ProjectProfile(context="Consultora de calidad"))

    _, _, llm = await _build(tmp_path, [document], lambda request: {}, ai_scope="missing_axes", taxonomy_manifest=manifest)

    system, user = (message["content"] for message in llm.proxy.requests[0].body["messages"])
    assert "- auditoria: Auditoría. Auditorías internas" in system
    assert "Consultora de calidad" in system and "SGC: sistema de gestión de la calidad" in system  # plantilla + proyecto (D11)
    for line in ("Título: Manual de calidad", "Carpeta: Calidad/2024", "Tipo de fichero: pdf", "- 1. Objeto", TEXT):
        assert line in user
    assert "Area" not in user  # solo los dos últimos niveles de la carpeta


@pytest.mark.asyncio
async def test_an_explicit_profile_replaces_the_composed_one(tmp_path) -> None:
    document = _document(tmp_path, "manual", "Manual de calidad")
    manifest = _manifest(profile=ProjectProfile(context="Consultora de calidad"))

    _, _, llm = await _build(
        tmp_path, [document], lambda request: {}, ai_scope="missing_axes", taxonomy_manifest=manifest, profile=ProjectProfile(glossary="Otro")
    )

    system = llm.proxy.requests[0].body["messages"][0]["content"]
    assert "Otro" in system and "Consultora" not in system
