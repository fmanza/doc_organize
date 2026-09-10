"""Tests de DomainClassifier (Sub-fase A, clasificación por reglas)."""

import json

import pytest

from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier, resolve_title_and_type, score_catalog
from doc_organize.core.models import ConversionResult


def _write_conversion_json(tmp_path, name: str, title: str, chunks: list[str]):
    json_path = tmp_path / f"{name}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": c} for c in chunks]}), encoding="utf-8")
    return json_path


@pytest.mark.asyncio
async def test_discovery_mode_uses_containing_folder_as_domain(tmp_path):
    source_dir = tmp_path / "Ciberseguridad"
    source_dir.mkdir()
    json_path = _write_conversion_json(tmp_path, "informe", "Informe anual", ["texto irrelevante"])
    document = ConversionResult(
        source_path=str(source_dir / "informe.pdf"),
        markdown_path=str(tmp_path / "informe.md"),
        json_path=str(json_path),
        success=True,
    )

    classified, unclassified = await DomainClassifier().classify([document])

    assert unclassified == []
    assert list(classified.keys()) == ["ciberseguridad"]
    assert classified["ciberseguridad"][0].title == "Informe anual"
    assert classified["ciberseguridad"][0].classified_by == "rules"


@pytest.mark.asyncio
async def test_catalog_mode_matches_by_keywords_in_chunks(tmp_path):
    source_dir = tmp_path / "varios"
    source_dir.mkdir()
    json_path = _write_conversion_json(tmp_path, "politica", "Política de calidad", ["gestión de calidad", "ISO 9001"])
    document = ConversionResult(
        source_path=str(source_dir / "politica.pdf"),
        markdown_path=str(tmp_path / "politica.md"),
        json_path=str(json_path),
        success=True,
    )

    classifier = DomainClassifier(candidate_domains=["calidad", "ciberseguridad"], threshold=0.5)
    classified, unclassified = await classifier.classify([document])

    assert unclassified == []
    assert list(classified.keys()) == ["calidad"]


@pytest.mark.asyncio
async def test_catalog_mode_never_invents_domain_outside_catalog(tmp_path):
    source_dir = tmp_path / "varios"
    source_dir.mkdir()
    json_path = _write_conversion_json(tmp_path, "receta", "Receta de cocina", ["ingredientes", "horno"])
    document = ConversionResult(
        source_path=str(source_dir / "receta.pdf"),
        markdown_path=str(tmp_path / "receta.md"),
        json_path=str(json_path),
        success=True,
    )

    classifier = DomainClassifier(candidate_domains=["calidad", "ciberseguridad"], threshold=0.5)
    classified, unclassified = await classifier.classify([document])

    assert classified == {}
    assert unclassified == [document]


@pytest.mark.asyncio
async def test_incomplete_artifacts_go_to_unclassified_not_raised(tmp_path):
    document = ConversionResult(
        source_path=str(tmp_path / "roto.pdf"),
        markdown_path=None,
        json_path=None,
        success=False,
        error="conversión fallida",
    )

    classified, unclassified = await DomainClassifier().classify([document])

    assert classified == {}
    assert unclassified == [document]


@pytest.mark.asyncio
async def test_missing_json_file_does_not_crash_the_whole_batch(tmp_path):
    source_dir = tmp_path / "Ciberseguridad"
    source_dir.mkdir()
    good_json = _write_conversion_json(tmp_path, "bueno", "Informe bueno", ["texto"])
    good_document = ConversionResult(
        source_path=str(source_dir / "bueno.pdf"),
        markdown_path=str(tmp_path / "bueno.md"),
        json_path=str(good_json),
        success=True,
    )
    broken_document = ConversionResult(
        source_path=str(source_dir / "roto.pdf"),
        markdown_path=str(tmp_path / "roto.md"),
        json_path=str(tmp_path / "no_existe.json"),
        success=True,
    )

    classified, unclassified = await DomainClassifier().classify([broken_document, good_document])

    assert unclassified == [broken_document]
    assert classified["ciberseguridad"][0].source_path == good_document.source_path


@pytest.mark.asyncio
async def test_malicious_candidate_domain_is_sanitized_before_becoming_a_slug(tmp_path):
    source_dir = tmp_path / "varios"
    source_dir.mkdir()
    # El texto del documento contiene literalmente la cadena maliciosa, para que
    # "gane" la clasificación si no se saneara (AUDIT_CODE, sesión 2026-09-08).
    json_path = _write_conversion_json(tmp_path, "doc", "Doc", ["../../otro-sitio"])
    document = ConversionResult(
        source_path=str(source_dir / "doc.pdf"),
        markdown_path=str(tmp_path / "doc.md"),
        json_path=str(json_path),
        success=True,
    )

    classifier = DomainClassifier(candidate_domains=["../../otro-sitio"], threshold=0.1)
    classified, _ = await classifier.classify([document])

    assert classifier.candidate_domains == ["otro-sitio"]
    for slug in classified:
        assert "/" not in slug
        assert ".." not in slug


@pytest.mark.asyncio
async def test_candidate_domains_dedupe_after_sanitizing_to_the_same_slug():
    classifier = DomainClassifier(candidate_domains=["Ciberseguridad", "ciberseguridad!!", "  ciberseguridad  "])

    assert classifier.candidate_domains == ["ciberseguridad"]


def test_resolve_title_and_type_falls_back_to_markdown_stem_and_extension():
    document = ConversionResult(source_path="/docs/Informe.PDF", markdown_path="/out/informe.md", json_path="/out/informe.json", success=True)

    title, document_type = resolve_title_and_type(document, None)

    assert title == "informe"
    assert document_type == "pdf"


def test_resolve_title_and_type_prefers_the_given_title_over_the_fallback():
    document = ConversionResult(source_path="/docs/x.pdf", markdown_path="/out/x.md", json_path="/out/x.json", success=True)

    title, document_type = resolve_title_and_type(document, "Título real")

    assert title == "Título real"
    assert document_type == "pdf"


def test_material_type_classifier_matches_by_keywords():
    classifier = MaterialTypeClassifier(["normativa", "procedimiento"], threshold=0.5)

    slug, score = classifier.classify_text(title="Política de calidad", chunks_text="normativa ISO 9001 vigente")

    assert slug == "normativa"
    assert score >= 0.5


def test_material_type_classifier_returns_none_below_threshold():
    classifier = MaterialTypeClassifier(["normativa", "procedimiento"], threshold=0.5)

    slug, score = classifier.classify_text(title="Receta de cocina", chunks_text="ingredientes y horno")

    assert slug is None
    assert score == 0.0


def test_material_type_classifier_sanitizes_slugs_like_domain_classifier():
    classifier = MaterialTypeClassifier(["Normativa", "normativa!!", "  normativa  "])

    assert classifier.material_types == ["normativa"]


def test_material_type_classifier_extra_keywords_contribute_to_the_score():
    """Sin `extra_keywords`, un texto que nunca menciona la palabra del slug ("normativa")
    no clasifica; con `extra_keywords={"normativa": ["ens"]}`, sí."""
    classifier = MaterialTypeClassifier(["normativa"], threshold=0.5)

    without_keywords = classifier.classify_text(title=None, chunks_text="controles de acceso ENS")
    with_keywords = classifier.classify_text(title=None, chunks_text="controles de acceso ENS", extra_keywords={"normativa": ["ens"]})

    assert without_keywords == (None, 0.0)
    assert with_keywords == ("normativa", 0.5)


def test_score_catalog_extra_keywords_use_the_sanitized_slug_as_key():
    slug, score = score_catalog(["ciberseguridad"], "informe sobre ens", folder_slug="", extra_keywords={"ciberseguridad": ["ENS"]})

    assert slug == "ciberseguridad"
    assert score == 0.5
