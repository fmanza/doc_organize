"""`check_taxonomy_rules` (M8, G5): cobertura y conflictos por reglas, iguales a los de `build` sin IA."""

import json

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.taxonomy_check import RulesCorpus, TaxonomyRulesReport, check_taxonomy_rules
from doc_organize.core.models import ConversionResult, Project, TaxonomyAxis, TaxonomyEntry
from tests.unit.taxonomy_helpers import two_axis_manifest

DOCUMENTS = {
    "Calidad/manual.pdf": ("Manual de calidad", "Manual del sistema de gestión de calidad conforme a ISO 9001."),
    "Auditorias/auditoria.pdf": ("Informe de auditoría", "Informe de la auditoría interna de calidad y seguridad."),
    "Seguridad/politica.pdf": ("Política de seguridad", "Política de seguridad de la información del ENS."),
    "Seguridad/plan.pdf": ("Plan de continuidad", "Plan de continuidad de la seguridad de la información."),
    "Otros/acta.pdf": ("Acta de reunión", "Acta de la reunión del comité."),
}


def make_documents(tmp_path: Path, documents: dict[str, tuple[str, str]] = DOCUMENTS) -> list[ConversionResult]:
    results = []
    for index, (relative, (title, text)) in enumerate(documents.items()):
        source = tmp_path / "entrada" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        json_path = tmp_path / f"doc{index}.json"
        json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}), encoding="utf-8")
        (tmp_path / f"doc{index}.md").write_text(title, encoding="utf-8")
        results.append(
            ConversionResult(source_path=str(source), markdown_path=str(tmp_path / f"doc{index}.md"), json_path=str(json_path), success=True)
        )
    return results


def base_manifest():
    return two_axis_manifest(
        [
            TaxonomyEntry(slug="calidad", name="Calidad", keywords=["iso 9001"]),
            TaxonomyEntry(slug="seguridad", name="Seguridad", keywords=["ens"]),
        ],
        [
            TaxonomyEntry(slug="manual", name="Manual"),
            TaxonomyEntry(slug="informe", name="Informe"),
            TaxonomyEntry(slug="politica", name="Política"),
            TaxonomyEntry(slug="procedimiento", name="Procedimiento"),
        ],
        extra_axes=[
            TaxonomyAxis(
                key="frameworks",
                name="Marcos",
                multiple=True,
                entries=[
                    TaxonomyEntry(slug="iso-9001", name="ISO 9001", keywords=["calidad"]),
                    TaxonomyEntry(slug="ens", name="ENS", keywords=["seguridad", "calidad"]),
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_coverage_matches_build_without_ai(tmp_path) -> None:
    documents = make_documents(tmp_path)
    manifest = base_manifest()
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())

    context = await ContextBuilder().build(project, documents, taxonomy_manifest=manifest, persist=False)
    report = check_taxonomy_rules(manifest, await RulesCorpus.load(documents))

    built = [document for domain in context.domains for document in domain.documents]
    for axis in manifest.axes:
        counts = Counter(value.slug for document in built for value in document.classification.axes.get(axis.key, []))
        found = report.axis(axis.key)
        assert found is not None
        assert found.covered == sum(1 for document in built if document.classification.axes.get(axis.key)), axis.key
        assert {slug: count for slug, count in found.entry_counts.items() if count} == dict(counts), axis.key


@pytest.mark.asyncio
async def test_report_details(tmp_path) -> None:
    report = check_taxonomy_rules(base_manifest(), await RulesCorpus.load(make_documents(tmp_path)))

    domains = report.axis("domains")
    assert domains is not None and report.documents == 5
    assert domains.covered == 4 and domains.uncovered_examples == ["Otros/acta.pdf"]
    # «auditoría interna de calidad y seguridad», fuera de sus carpetas: calidad y seguridad empatan → conflicto
    assert domains.conflicts == 1 and domains.conflict_examples == {"Auditorias/auditoria.pdf": ["calidad", "seguridad"]}
    materials = report.axis("material_types")
    assert materials is not None and materials.empty_entries == ["procedimiento"]
    frameworks = report.axis("frameworks")
    assert frameworks is not None and frameworks.conflicts == 0  # varios valores: no hay conflicto
    assert frameworks.shared_terms == {"calidad": ["iso-9001", "ens"]}
    assert "| domains | 5 | 80,0 % | 1 | 0 |" in report.to_markdown()


@pytest.mark.asyncio
async def test_a_better_manifest_improves_on_the_base(tmp_path) -> None:
    corpus = await RulesCorpus.load(make_documents(tmp_path))
    base = base_manifest()
    better = base.model_copy(
        update={
            "axes": [
                TaxonomyAxis(
                    key="domains",
                    name="Dominios",
                    organizes="folder",
                    entries=[
                        TaxonomyEntry(slug="calidad", name="Calidad", keywords=["iso 9001", "auditoría"]),
                        TaxonomyEntry(slug="seguridad", name="Seguridad", keywords=["información"]),
                        TaxonomyEntry(slug="gobierno", name="Gobierno", keywords=["comité"]),
                    ],
                ),
                *base.axes[1:],
            ]
        }
    )

    before, after = check_taxonomy_rules(base, corpus), check_taxonomy_rules(better, corpus)

    assert after.axis("domains").covered == 5 and after.axis("domains").conflicts == 0  # type: ignore[union-attr]
    assert after.improves_on(before) and not before.improves_on(after) and not before.improves_on(before)


@pytest.mark.asyncio
async def test_unreadable_documents_are_left_out(tmp_path) -> None:
    documents = make_documents(tmp_path)
    Path(documents[0].json_path).write_text("{no es json", encoding="utf-8")  # type: ignore[arg-type]

    corpus = await RulesCorpus.load(documents)

    assert corpus.unreadable == ["Calidad/manual.pdf"] and len(corpus.documents) == 4
    assert check_taxonomy_rules(base_manifest(), corpus).unreadable == 1


def test_empty_report_coverage_is_zero() -> None:
    assert TaxonomyRulesReport().improves_on(TaxonomyRulesReport()) is False


@pytest.mark.asyncio
async def test_unused_keywords(tmp_path) -> None:
    base = base_manifest()
    domains = base.axes[0].model_copy(
        update={"entries": [TaxonomyEntry(slug="calidad", name="Calidad", keywords=["iso 9001", "gestion-calidad"]), *base.axes[0].entries[1:]]}
    )
    frameworks = base.axes[2].model_copy(update={"entries": [TaxonomyEntry(slug="ens", name="ENS", keywords=["seguridad", "esquema nacional"])]})
    manifest = base.model_copy(update={"axes": [domains, base.axes[1], frameworks]})

    report = check_taxonomy_rules(manifest, await RulesCorpus.load(make_documents(tmp_path)))

    assert report.axis("domains").unused_keywords == {"calidad": ["gestion-calidad"]}  # type: ignore[union-attr]
    assert report.axis("frameworks").unused_keywords == {"ens": ["esquema nacional"]}  # type: ignore[union-attr]
    assert check_taxonomy_rules(base_manifest(), await RulesCorpus.load(make_documents(tmp_path))).axis("domains").unused_keywords == {}  # type: ignore[union-attr]
