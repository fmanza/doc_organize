"""Peticiones de la web en W3 (M10): la cita de la IA también sin manifiesto, y el perfil compuesto desde un texto."""

import json

from datetime import UTC, datetime

import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.project_profile import compose_profile_text
from doc_organize.core.models import ConversionResult, Project, ProjectProfile
from tests.unit.fake_llm import FakeRequest, fake_client

TEXT = "Plan de respuesta ante incidentes informáticos del centro, con contactos y pasos."


def _document(tmp_path) -> ConversionResult:
    source = tmp_path / "entrada" / "Varios" / "plan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF")
    (tmp_path / "plan.json").write_text(json.dumps({"title": "Plan", "chunks": [{"text": TEXT}]}), encoding="utf-8")
    (tmp_path / "plan.md").write_text(f"# Plan\n\n{TEXT}\n", encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(tmp_path / "plan.md"), json_path=str(tmp_path / "plan.json"), success=True)


def _answer(evidence: str):
    def respond(request: FakeRequest) -> dict:
        return {request.axes[0]: {"values": [{"value": "seguridad", "confidence": 0.9, "evidence": evidence}]}}

    return respond


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("evidence", "verified", "confident"),
    [("respuesta ante incidentes informáticos", True, True), ("un texto que no está en el documento", False, False)],
)
async def test_ai_evidence_is_kept_without_manifest(tmp_path, evidence, verified, confident) -> None:
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())

    context = await ContextBuilder().build(
        project,
        [_document(tmp_path)],
        candidate_domains=["calidad", "seguridad"],
        llm=fake_client(classify=_answer(evidence)),
        ai_scope="unclassified",
        ai_cache=False,
        persist=False,
    )

    [domain] = context.domains
    [document] = domain.documents
    [value] = document.classification.axes["domains"]
    assert (domain.slug, value.slug, value.classified_by, value.evidence, value.evidence_verified) == (
        "seguridad",
        "seguridad",
        "ai",
        evidence,
        verified,
    )
    assert value.name == domain.name
    assert (value.confidence >= context.ai_fallback_threshold) is confident  # sin verificar, por debajo del umbral (D10)


def test_compose_profile_text() -> None:
    template = ProjectProfile(context="SGSI de un centro", examples=["Política → gobernanza"])

    composed = compose_profile_text(template, "## Contexto del proyecto\n\nCentro de datos.\n\n## Ejemplos\n- Acta → registro\n")

    assert composed is not None and composed.context == "SGSI de un centro\n\nCentro de datos."
    assert composed.examples == ["Política → gobernanza", "Acta → registro"]
    assert compose_profile_text(None, "") is None and compose_profile_text(template, None) == template
