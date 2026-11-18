"""Clasificación por ejes (M1, A2 y A3): reglas de los ejes que etiquetan, `classification` en cada documento,
`context.json` v2 y lectura de contextos de 1.x."""

import json

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from doc_organize import ContextBuilder, ContextRegistry, parse_taxonomy_template
from doc_organize.context.axis_rules import AxisRuleScorer, FoldedText, fold
from doc_organize.core.models import (
    AxisValue,
    Context,
    ConversionResult,
    Domain,
    DomainDocument,
    Project,
    TaxonomyAxis,
    TaxonomyClassificationResult,
    TaxonomyEntry,
)
from tests.unit.taxonomy_helpers import two_axis_manifest

#: Plantilla con la forma de la de CALIDAD_VD (1.x, ejes implícitos) y sus marcos normativos tal como están escritos:
#: `seguridad` y `españa` repetidos entre entradas, `ENS` sin «Esquema Nacional de Seguridad» en las palabras clave.
CALIDAD_VD_LIKE = """---
title: Normas y gobernanza
domains:
  - slug: seguridad-informacion
    name: Seguridad de la información
    keywords: [seguridad, sgsi]
  - slug: calidad
    name: Calidad
    keywords: [calidad]
normative_frameworks:
  - slug: iso-27001
    name: ISO/IEC 27001
    keywords: [SGSI, seguridad, información, ciberseguridad]
  - slug: iso-9001
    name: ISO 9001
    keywords: [calidad, procesos, gestión de calidad]
  - slug: iso-20000
    name: ISO/IEC 20000
    keywords: [ITSM, servicios, ti]
  - slug: iso-22301
    name: ISO 22301
    keywords: [continuidad, bcp, resilencia]
  - slug: iso-14001
    name: ISO 14001
    keywords: [ambiental, sostenibilidad, carbono]
  - slug: ens
    name: ENS - Esquema Nacional de Seguridad
    keywords: [ENS, españa, seguridad, administración pública]
  - slug: lssi-ce
    name: LSSI-CE
    keywords: [LSSI, españa, servicios digitales]
  - slug: lo-3-2018
    name: LO 3/2018 (LOPDGDD)
    keywords: [LOPDGDD, españa, datos, privacidad]
  - slug: nist-csf
    name: NIST Cybersecurity Framework
    keywords: [NIST, framework, ciberseguridad]
material_types:
  - slug: procedimiento
    name: Procedimiento
    keywords: [procedimiento]
  - slug: politica
    name: Política
    keywords: [politica]
---
"""


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, stem: str, title: str, text: str = "", folder: str = "docs") -> ConversionResult:
    (tmp_path / folder).mkdir(exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}] if text else []}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(title, encoding="utf-8")
    return ConversionResult(
        source_path=str(tmp_path / folder / f"{stem}.pdf"), markdown_path=str(tmp_path / f"{stem}.md"), json_path=str(json_path), success=True
    )


def _frameworks_scorer() -> AxisRuleScorer:
    axis = parse_taxonomy_template(CALIDAD_VD_LIKE).axis("normative_frameworks")
    assert axis is not None
    return AxisRuleScorer(axis, threshold=0.5)


def _entries(*slugs: str) -> list[TaxonomyEntry]:
    return [TaxonomyEntry(slug=slug, name=slug.title()) for slug in slugs]


# --- A2: reglas de los ejes que etiquetan ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Tabla del AUDIT_PLAN del plan de facetas (C1-C3), con la plantilla tal como está escrita.
        ("Política de calidad ISO 9001 del departamento", ["iso-9001"]),
        ("Procedimiento de ensayos sensibles de laboratorio", []),
        ("Declaración de aplicabilidad del SGSI conforme a ISO/IEC 27001 y al Esquema Nacional de Seguridad", ["iso-27001", "ens"]),
    ],
)
def test_frameworks_by_whole_words_without_shared_terms(text: str, expected: list[str]) -> None:
    values = _frameworks_scorer().classify(FoldedText.of(text))

    assert [value.slug for value in values] == expected
    assert all(value.classified_by == "rules" for value in values)


def test_shared_terms_do_not_count_and_slug_remainder_does() -> None:
    scorer = _frameworks_scorer()

    assert "seguridad" not in scorer.terms("ens")  # también en iso-27001
    assert "espana" not in scorer.terms("ens")  # también en lssi-ce y lo-3-2018
    assert "iso" not in scorer.terms("iso-9001")  # todas las ISO lo tienen
    assert "9001" in scorer.terms("iso-9001")  # el slug sin su prefijo compartido
    assert "esquema nacional de seguridad" in scorer.terms("ens")  # parte del nombre


def test_confidence_grows_with_distinct_terms_not_with_catalog_size() -> None:
    axis = TaxonomyAxis(
        key="frameworks",
        name="Marcos",
        multiple=True,
        entries=[TaxonomyEntry(slug="ens", name="ENS", keywords=["Esquema Nacional de Seguridad", "CCN", "categoría media", "uno", "dos", "tres"])],
    )
    scorer = AxisRuleScorer(axis, threshold=0.5)

    def confidence(text: str) -> float | None:
        values = scorer.classify(FoldedText.of(text))
        return values[0].confidence if values else None

    assert confidence("el ENS") == 0.6
    assert confidence("el ENS del CCN") == 0.8
    assert confidence("ENS del CCN en categoría media") == 1.0
    assert confidence("nada que ver") is None


def test_multiple_axis_keeps_at_most_five_values_and_single_axis_only_the_best() -> None:
    entries = [TaxonomyEntry(slug=f"marco-{i}", name=f"Marco {i}", keywords=[f"clave{i}"]) for i in range(7)]
    text = FoldedText.of("clave0 clave1 clave2 clave3 clave4 clave5 clave6 Marco 6")

    multiple = AxisRuleScorer(TaxonomyAxis(key="m", name="M", multiple=True, entries=entries), threshold=0.5).classify(text)
    single = AxisRuleScorer(TaxonomyAxis(key="s", name="S", entries=entries), threshold=0.5).classify(text)

    assert len(multiple) == 5
    assert multiple[0].slug == "marco-6"  # dos términos: va primero
    assert [value.slug for value in multiple[1:]] == ["marco-0", "marco-1", "marco-2", "marco-3"]  # empate: orden del catálogo
    assert [value.slug for value in single] == ["marco-6"]


def test_axis_threshold_and_rules_false() -> None:
    entries = [TaxonomyEntry(slug="registro", name="Registro de evidencia", keywords=["registro"])]
    text = FoldedText.of("Registro de actividad")

    assert AxisRuleScorer(TaxonomyAxis(key="e", name="E", threshold=0.7, entries=entries), threshold=0.5).classify(text) == []
    assert AxisRuleScorer(TaxonomyAxis(key="e", name="E", rules=False, entries=entries), threshold=0.5).classify(text) == []
    assert len(AxisRuleScorer(TaxonomyAxis(key="e", name="E", entries=entries), threshold=0.5).classify(text)) == 1


def test_fold_removes_accents_case_and_punctuation() -> None:
    assert fold("ADMINISTRACIÓN  Pública/ISO-27001.") == "administracion publica iso 27001"


# --- A3: clasificación en el contexto --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m1_acceptance_calidad_vd_like_template_classifies_frameworks(tmp_path) -> None:
    """Puerta de M1: la plantilla implícita migra y clasifica `iso-27001` y `ens` en el documento que menciona los dos;
    «ensayos sensibles» no da `ens`; dominio y tipo de material, como siempre."""
    project = _project(tmp_path)
    manifest = parse_taxonomy_template(CALIDAD_VD_LIKE)
    both = _document(
        tmp_path, "soa", "Declaración de aplicabilidad", "Procedimiento del SGSI conforme a ISO/IEC 27001 y al Esquema Nacional de Seguridad"
    )
    lab = _document(tmp_path, "lab", "Ensayos", "Procedimiento de ensayos sensibles de laboratorio de calidad")

    context = await ContextBuilder().build(project, [both, lab], taxonomy_manifest=manifest)

    documents = {document.source_path: document for domain in context.domains for document in domain.documents}
    soa, laboratory = documents[both.source_path], documents[lab.source_path]
    assert soa.classification.slugs("normative_frameworks") == ["iso-27001", "ens"]
    assert "ens" not in laboratory.classification.slugs("normative_frameworks")
    assert soa.classification.slugs("domains") == ["seguridad-informacion"]
    assert soa.classification.slugs("material_types") == [soa.material_type] == ["procedimiento"]
    assert laboratory.classification.slugs("domains") == ["calidad"]


@pytest.mark.asyncio
async def test_context_v2_persists_axes_without_keywords_and_classification(tmp_path) -> None:
    project = _project(tmp_path)
    frameworks = TaxonomyAxis(
        key="normative_frameworks", name="Marcos", multiple=True, entries=[TaxonomyEntry(slug="ens", name="ENS", keywords=["Esquema Nacional"])]
    )
    manifest = two_axis_manifest(
        [TaxonomyEntry(slug="ciberseguridad", name="Ciberseguridad", keywords=["ciberseguridad"])],
        [TaxonomyEntry(slug="normativa", name="Normativa", keywords=["normativa"], examples=["Real Decreto"])],
        extra_axes=[frameworks],
    )
    matched = _document(tmp_path, "a", "Normativa de ciberseguridad", "Esquema Nacional de Seguridad")
    unmatched = _document(tmp_path, "b", "Receta", "pollo al horno")

    await ContextBuilder().build(project, [matched, unmatched], taxonomy_manifest=manifest)
    context = await ContextRegistry().load_context(project)

    assert context.schema_version == 2
    assert [axis.key for axis in context.taxonomy_axes] == ["domains", "material_types", "normative_frameworks"]
    assert all(not entry.keywords and not entry.examples for axis in context.taxonomy_axes for entry in axis.entries)
    documents = {document.source_path: document for domain in context.domains for document in domain.documents}
    assert documents[matched.source_path].classification.axes == {
        "domains": [
            AxisValue(slug="ciberseguridad", name="Ciberseguridad", confidence=documents[matched.source_path].confidence, classified_by="rules")
        ],
        "material_types": [
            AxisValue(
                slug="normativa", name="Normativa", confidence=documents[matched.source_path].material_type_confidence or 0, classified_by="rules"
            )
        ],
        "normative_frameworks": [AxisValue(slug="ens", name="ENS", confidence=0.6, classified_by="rules")],
    }
    # En «sin clasificar» los ejes organizadores quedan vacíos (se evaluaron, sin valor).
    assert documents[unmatched.source_path].classification.axes == {"domains": [], "material_types": [], "normative_frameworks": []}


class _StubTaxonomyAI:
    config = SimpleNamespace(model="stub")

    async def classify(self, **_: object) -> TaxonomyClassificationResult:
        return TaxonomyClassificationResult(domain="calidad", domain_confidence=0.9, material_type="politica", material_type_confidence=0.7)


@pytest.mark.asyncio
async def test_ai_marks_only_the_axis_it_decided(tmp_path) -> None:
    project = _project(tmp_path)
    manifest = two_axis_manifest(
        _entries("calidad", "seguridad"), [*_entries("politica"), TaxonomyEntry(slug="manual", name="Manual", keywords=["manual"])]
    )
    document = _document(tmp_path, "m", "Manual", "manual sin dominio")

    context = await ContextBuilder().build(
        project, [document], taxonomy_manifest=manifest, ai_classification_enabled=True, taxonomy_classification_client=_StubTaxonomyAI()
    )

    result = context.domains[0].documents[0]
    assert result.classification.axes["domains"] == [AxisValue(slug="calidad", name="Calidad", confidence=0.9, classified_by="ai")]
    assert result.classification.axes["material_types"][0].classified_by == "rules"  # «manual» ya lo resolvieron las reglas
    assert result.classification.slugs("material_types") == ["manual"]


@pytest.mark.asyncio
async def test_without_manifest_the_single_axis_is_domains(tmp_path) -> None:
    project = _project(tmp_path)
    document = _document(tmp_path, "informe", "Informe", folder="Ciberseguridad")

    context = await ContextBuilder().build(project, [document])

    assert [(axis.key, axis.organizes, [entry.slug for entry in axis.entries]) for axis in context.taxonomy_axes] == [
        ("domains", "folder", ["ciberseguridad"])
    ]
    assert context.domains[0].documents[0].classification.slugs("domains") == ["ciberseguridad"]


# --- Lectura de contextos de 1.x -------------------------------------------------------------------------------------


def _v1_document(**kwargs: object) -> DomainDocument:
    base: dict[str, object] = {
        "source_path": "/p/a.pdf",
        "markdown_path": "/p/a.md",
        "json_path": "/p/a.json",
        "title": "A",
        "document_type": "pdf",
        "confidence": 0.7,
    }
    return DomainDocument(**(base | kwargs))  # type: ignore[arg-type]


def test_v1_context_is_migrated_when_read() -> None:
    rules = _v1_document(material_type="politica", material_type_name="Política", rules_domain="calidad", rules_confidence=0.7)
    ai_domain = _v1_document(
        source_path="/p/b.pdf", material_type="politica", classified_by="ai", rules_domain=None, ai_domain="calidad", material_type_confidence=0.6
    )
    ai_material = _v1_document(
        source_path="/p/c.pdf", material_type="manual", classified_by="ai", rules_domain="calidad", rules_confidence=0.9, ai_domain="calidad"
    )
    pending = _v1_document(source_path="/p/d.pdf", material_type="sin-clasificar")
    payload = {
        "project_name": "P",
        "taxonomy_manifest_used": True,
        "created_at": "a",
        "updated_at": "b",
        "domains": [
            Domain(slug="calidad", name="Calidad", documents=[rules, ai_domain, ai_material]).model_dump(),
            Domain(slug="sin-clasificar", name="Sin Clasificar", documents=[pending]).model_dump(),
        ],
    }
    for domain in payload["domains"]:  # type: ignore[attr-defined]
        for document in domain["documents"]:
            del document["classification"]  # como un index.json de 1.x

    context = Context.model_validate(payload)

    assert context.schema_version == 2
    assert [(axis.key, [entry.slug for entry in axis.entries]) for axis in context.taxonomy_axes] == [
        ("domains", ["calidad"]),
        ("material_types", ["politica", "manual"]),
    ]
    docs = context.domains[0].documents
    assert docs[0].classification.axes["domains"][0].classified_by == "rules"
    assert docs[0].classification.axes["material_types"][0] == AxisValue(slug="politica", name="Política", confidence=0.7, classified_by="rules")
    assert docs[1].classification.axes["domains"][0].classified_by == "ai"
    assert docs[1].classification.axes["material_types"][0].classified_by == "rules"
    assert docs[2].classification.axes["domains"][0].classified_by == "rules"
    assert docs[2].classification.axes["material_types"][0].classified_by == "ai"
    assert context.domains[1].documents[0].classification.axes == {"domains": [], "material_types": []}


def test_v2_context_is_not_migrated_again() -> None:
    context = Context(
        schema_version=2, project_name="P", created_at="a", updated_at="b", domains=[Domain(slug="x", name="X", documents=[_v1_document()])]
    )

    assert context.taxonomy_axes == []
    assert context.domains[0].documents[0].classification.axes == {}
