"""Medir la clasificación (2.6.0, F0 de precisión del contexto): métricas por valor, tramos de confianza y comparación
pareada de dos clasificaciones."""

import pytest

from doc_organize import (
    UNCLASSIFIED_SLUG,
    ClassificationComparison,
    EvaluationReport,
    GoldLabel,
    GoldStandard,
    compare_classifications,
    evaluate_classification,
)
from doc_organize.context.evaluation import NONE_LABEL
from doc_organize.core.models import (
    AxisValue,
    Context,
    DocumentClassification,
    Domain,
    DomainDocument,
    TaxonomyAxis,
    TaxonomyEntry,
    UnclassifiedDocument,
)

ROOT = "/mnt/documentation/entrada_vd"


def _document(path: str, slugs: list[str], by: str = "rules", confidence: float = 0.8) -> DomainDocument:
    values = [AxisValue(slug=slug, name=slug, confidence=confidence, classified_by=by) for slug in slugs]  # type: ignore[arg-type]
    return DomainDocument(
        source_path=f"{ROOT}/{path}",
        markdown_path="x.md",
        json_path="x.json",
        title=path,
        document_type="pdf",
        confidence=confidence,
        classification=DocumentClassification(axes={"domains": values}),
    )


def _context(*documents: DomainDocument, unclassified: tuple[str, ...] = ()) -> Context:
    axis = TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=[TaxonomyEntry(slug="calidad", name="Calidad")])
    return Context(
        project_name="demo",
        created_at="2026-11-27T00:00:00+00:00",
        updated_at="2026-11-27T00:00:00+00:00",
        taxonomy_axes=[axis],
        domains=[Domain(slug="calidad", name="Calidad", documents=list(documents))],
        unclassified_details=[
            UnclassifiedDocument(source_path=f"{ROOT}/{path}", document_type="pdf", reason="below_threshold") for path in unclassified
        ],
    )


def _gold(**labels: list[str]) -> GoldStandard:
    return GoldStandard(labels=[GoldLabel(document=f"{name}.pdf", axes={"domains": values}) for name, values in labels.items()])


# --- métricas por valor (E1) -----------------------------------------------------------------------------------------


def test_per_value_metrics_macro_f1_and_selective_accuracy() -> None:
    context = _context(
        _document("a.pdf", ["calidad"]),
        _document("b.pdf", ["calidad"], by="ai"),
        _document("c.pdf", ["calidad"]),
        _document("d.pdf", []),
        unclassified=("e.pdf",),
    )
    gold = _gold(a=["calidad"], b=["seguridad"], c=["seguridad"], d=[], e=["calidad"])

    domains = evaluate_classification(context, gold).axes["domains"]

    assert [(m.value, m.support, m.assigned, m.correct, m.precision, m.recall, m.f1) for m in domains.per_value] == [
        ("calidad", 2, 3, 1, 0.3333, 0.5, 0.4),
        ("seguridad", 2, 0, 0, None, 0.0, 0.0),
    ]
    assert domains.macro_f1 == 0.2
    assert domains.selective_accuracy == 0.3333  # 1 de los 3 con valor; d y e no cuentan como error
    assert (domains.accuracy, domains.coverage) == (0.4, 0.6)  # lo de siempre no cambia
    assert domains.confusion_matrix == {
        "calidad": {"calidad": 1, NONE_LABEL: 1},
        NONE_LABEL: {NONE_LABEL: 1},
        "seguridad": {"calidad": 2},
    }


def test_values_only_assigned_do_not_enter_the_macro_average() -> None:
    context = _context(_document("a.pdf", ["calidad"]), _document("b.pdf", ["otro"]))

    domains = evaluate_classification(context, _gold(a=["calidad"], b=["calidad"])).axes["domains"]

    assert [(m.value, m.support, m.f1) for m in domains.per_value] == [("calidad", 2, round(2 / 3, 4)), ("otro", 0, 0.0)]
    assert domains.macro_f1 == round(2 / 3, 4)


def test_accuracy_by_confidence_is_split_by_phase_and_bin() -> None:
    context = _context(
        _document("a.pdf", ["calidad"], confidence=0.5),  # [0,5, 0,6)
        _document("b.pdf", ["calidad"], confidence=0.55),
        _document("c.pdf", ["calidad"], by="ai", confidence=1.0),  # el último tramo incluye el 1,0
        _document("d.pdf", ["calidad"], confidence=0.2),
        _document("e.pdf", []),  # sin valor: sin tramo
    )
    gold = _gold(a=["calidad"], b=["seguridad"], c=["calidad"], d=["calidad"], e=["calidad"])

    bins = evaluate_classification(context, gold).axes["domains"].accuracy_by_confidence

    assert [(b.classified_by, b.lower, b.upper, b.labelled, b.accuracy) for b in bins] == [
        ("ai", 0.9, 1.0, 1, 1.0),
        ("rules", 0.0, 0.5, 1, 1.0),
        ("rules", 0.5, 0.6, 2, 0.5),
    ]


def test_detailed_markdown_adds_a_table_per_value() -> None:
    report = evaluate_classification(_context(_document("a.pdf", ["calidad"])), _gold(a=["calidad"]))

    markdown = report.to_markdown(detail=True)

    assert markdown.startswith(report.to_markdown())
    assert "| calidad | 1 | 1 | 1 | 1.0 | 1.0 | 1.0 |" in markdown
    assert "F1 macro 1.0" in markdown


def test_reports_serialized_by_2_5_still_validate() -> None:
    """C5: un informe guardado por 2.5.0 (sin los campos nuevos) se sigue leyendo."""
    old = {
        "axes": {
            "domains": {
                "axis": "domains",
                "multiple": False,
                "labelled": 2,
                "accuracy": 0.5,
                "coverage": 1.0,
                "precision": 0.5,
                "recall": 0.5,
                "accuracy_by_classified_by": {"rules": 0.5},
                "labelled_by_classified_by": {"rules": 2},
                "confusions": [{"label": "a", "assigned": "b", "count": 1}],
            }
        },
        "documents": 2,
        "matched": 2,
        "missing_documents": [],
    }

    axis = EvaluationReport.model_validate(old).axes["domains"]

    assert (axis.macro_f1, axis.per_value, axis.confusion_matrix, axis.accuracy_by_confidence) == (None, [], {}, [])


# --- comparación pareada (E2) ----------------------------------------------------------------------------------------


def _contexts_with_hits(hits: list[bool]) -> tuple[Context, GoldStandard]:
    documents = [_document(f"d{i}.pdf", ["calidad" if hit else "otro"]) for i, hit in enumerate(hits)]
    return _context(*documents), GoldStandard(labels=[GoldLabel(document=f"d{i}.pdf", axes={"domains": ["calidad"]}) for i in range(len(hits))])


def test_identical_classifications_are_non_inferior_but_not_better() -> None:
    context, gold = _contexts_with_hits([True, False] * 10)

    comparison = compare_classifications(context, context, gold)

    domains = comparison.axes["domains"]
    assert domains.paired == 20
    assert (domains.accuracy.baseline, domains.accuracy.candidate, domains.accuracy.difference) == (0.5, 0.5, 0.0)
    assert (domains.accuracy.ci_low, domains.accuracy.ci_high) == (0.0, 0.0)
    assert (domains.discordant_baseline_only, domains.discordant_candidate_only, domains.p_value_mcnemar) == (0, 0, 1.0)
    assert (comparison.non_inferior, comparison.improved) == (True, False)


def test_clear_improvement_excludes_zero_and_mcnemar_is_exact() -> None:
    baseline, gold = _contexts_with_hits([False] * 10)
    candidate, _ = _contexts_with_hits([True] * 10)

    comparison = compare_classifications(baseline, candidate, gold)

    domains = comparison.axes["domains"]
    assert domains.accuracy.difference == 1.0 and domains.accuracy.ci_low == 1.0
    assert (domains.discordant_baseline_only, domains.discordant_candidate_only) == (0, 10)
    assert domains.p_value_mcnemar == round(2 / 2**10, 4)
    assert (comparison.non_inferior, comparison.improved) == (True, True)


def test_a_worse_candidate_is_not_non_inferior() -> None:
    baseline, gold = _contexts_with_hits([True] * 30)
    candidate, _ = _contexts_with_hits([True] * 20 + [False] * 10)

    comparison = compare_classifications(baseline, candidate, gold, margin=0.03)

    assert comparison.axes["domains"].accuracy.ci_high is not None and comparison.axes["domains"].accuracy.ci_high < 0
    assert (comparison.non_inferior, comparison.improved) == (False, False)


def test_same_seed_same_interval_and_another_seed_may_differ() -> None:
    baseline, gold = _contexts_with_hits([True, False, False, True, False] * 6)
    candidate, _ = _contexts_with_hits([True, True, False, True, False] * 6)

    first = compare_classifications(baseline, candidate, gold, seed=7, resamples=300)
    again = compare_classifications(baseline, candidate, gold, seed=7, resamples=300)

    assert first == again
    assert first.seed == 7 and first.resamples == 300


def test_abstention_counts_in_coverage_not_in_selective_accuracy() -> None:
    baseline = _context(_document("a.pdf", ["calidad"]), _document("b.pdf", ["otro"]))
    candidate = _context(_document("a.pdf", ["calidad"]), _document("b.pdf", []))  # se abstiene en vez de fallar
    gold = _gold(a=["calidad"], b=["calidad"])

    domains = compare_classifications(baseline, candidate, gold).axes["domains"]

    assert (domains.accuracy.baseline, domains.accuracy.candidate) == (0.5, 0.5)
    assert (domains.selective_accuracy.baseline, domains.selective_accuracy.candidate) == (0.5, 1.0)
    assert (domains.coverage.baseline, domains.coverage.candidate) == (1.0, 0.5)


def test_documents_missing_in_either_classification_are_unpaired() -> None:
    baseline = _context(_document("a.pdf", ["calidad"]), _document("b.pdf", ["calidad"]))
    candidate = _context(_document("a.pdf", ["calidad"]), _document("c.pdf", ["calidad"]))
    gold = _gold(a=["calidad"], b=["calidad"], c=["calidad"])

    comparison = compare_classifications(baseline, candidate, gold, roots=[ROOT])

    assert comparison.unpaired == ["b.pdf", "c.pdf"]
    assert comparison.axes["domains"].paired == 1


def test_nothing_paired_is_neither_non_inferior_nor_improved() -> None:
    comparison = compare_classifications(_context(), _context(), _gold(a=["calidad"]))

    assert (comparison.axes, comparison.non_inferior, comparison.improved) == ({}, False, False)


@pytest.mark.parametrize(
    "options",
    [{"resamples": 0}, {"margin": -0.01}, {"confidence_level": 1.0}, {"confidence_level": 0.0}],
)
def test_invalid_options_raise(options: dict[str, float]) -> None:
    context = _context()

    with pytest.raises(ValueError):
        compare_classifications(context, context, _gold(), **options)  # type: ignore[arg-type]


def test_comparison_markdown_has_one_row_per_axis() -> None:
    baseline, gold = _contexts_with_hits([False] * 5)
    candidate, _ = _contexts_with_hits([True] * 5)

    markdown = compare_classifications(baseline, candidate, gold).to_markdown()

    assert markdown.splitlines()[0].startswith("| Eje | Pareados | Partida | Candidata |")
    assert markdown.splitlines()[2].startswith("| domains | 5 | 0.0 | 1.0 | 1.0 | [1.0, 1.0] |")
    assert isinstance(
        ClassificationComparison.model_validate_json(compare_classifications(baseline, candidate, gold).model_dump_json()), ClassificationComparison
    )


# --- marcador (E4) ---------------------------------------------------------------------------------------------------


def test_placeholder_slug_is_public_and_flags_the_domain() -> None:
    assert UNCLASSIFIED_SLUG == "sin-clasificar"
    assert Domain(slug=UNCLASSIFIED_SLUG, name="Sin Clasificar").is_placeholder is True
    assert Domain(slug="calidad", name="Calidad").is_placeholder is False
    assert "is_placeholder" not in Domain(slug=UNCLASSIFIED_SLUG, name="x").model_dump()  # no cambia context.json
