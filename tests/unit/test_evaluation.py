"""Evaluación contra una referencia (M6, G3): Excel de la línea base, métricas por eje y claves de documento."""

import pytest

from openpyxl import Workbook

from doc_organize import AxisEvaluation, EvaluationReport, GoldLabel, GoldStandard, evaluate_classification, load_gold_xlsx
from doc_organize.context.evaluation import NONE_LABEL, UNCLASSIFIED, common_root
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


def _values(slugs: list[str], by: str = "rules") -> list[AxisValue]:
    return [AxisValue(slug=slug, name=slug, confidence=0.8, classified_by=by) for slug in slugs]  # type: ignore[arg-type]


def _document(path: str, axes: dict[str, list[AxisValue]]) -> DomainDocument:
    return DomainDocument(
        source_path=f"{ROOT}/{path}",
        markdown_path="x.md",
        json_path="x.json",
        title=path,
        document_type="pdf",
        confidence=0.8,
        classification=DocumentClassification(axes=axes),
    )


def _context(*documents: DomainDocument, unclassified: tuple[str, ...] = ()) -> Context:
    axes = [
        TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=[TaxonomyEntry(slug="calidad", name="Calidad")]),
        TaxonomyAxis(key="frameworks", name="Marcos", multiple=True, entries=[TaxonomyEntry(slug="ens", name="ENS")]),
    ]
    return Context(
        project_name="demo",
        created_at="2026-11-18T00:00:00+00:00",
        updated_at="2026-11-18T00:00:00+00:00",
        taxonomy_axes=axes,
        domains=[Domain(slug="calidad", name="Calidad", documents=list(documents))],
        unclassified_details=[
            UnclassifiedDocument(source_path=f"{ROOT}/{path}", document_type="pdf", reason="below_threshold") for path in unclassified
        ],
    )


def test_single_axis_metrics_by_who_and_confusions() -> None:
    context = _context(
        _document("Calidad/a.pdf", {"domains": _values(["calidad"])}),
        _document("Calidad/b.pdf", {"domains": _values(["calidad"], "ai")}),
        _document("ENS/c.pdf", {"domains": _values(["calidad"])}),
        _document("ENS/d.pdf", {"domains": []}),
        unclassified=("Otros/e.pdf",),
    )
    gold = GoldStandard(
        labels=[
            GoldLabel(document="Calidad/a.pdf", axes={"domains": ["calidad"]}),
            GoldLabel(document="Calidad/b.pdf", axes={"domains": ["seguridad"]}),
            GoldLabel(document="ENS/c.pdf", axes={"domains": ["seguridad"]}),
            GoldLabel(document="ENS/d.pdf", axes={"domains": []}),  # «ninguno»: vacío es lo correcto
            GoldLabel(document="Otros/e.pdf", axes={"domains": ["calidad"]}),
            GoldLabel(document="Fuera/f.pdf", axes={"domains": ["calidad"]}),
        ]
    )

    report = evaluate_classification(context, gold)

    domains = report.axes["domains"]
    assert (report.documents, report.matched, report.missing_documents) == (5, 5, ["Fuera/f.pdf"])
    assert (domains.labelled, domains.accuracy, domains.coverage) == (5, 0.4, 0.6)
    assert (domains.precision, domains.recall) == (round(1 / 3, 4), 0.25)
    assert domains.accuracy_by_classified_by == {"ai": 0.0, "rules": 0.5, UNCLASSIFIED: 0.5}
    assert domains.labelled_by_classified_by == {"ai": 1, "rules": 2, UNCLASSIFIED: 2}
    assert [(c.label, c.assigned, c.count) for c in domains.confusions] == [("seguridad", "calidad", 2), ("calidad", NONE_LABEL, 1)]
    assert domains.multiple is False


def test_multiple_axis_counts_exact_sets_precision_and_recall() -> None:
    context = _context(
        _document("a.pdf", {"frameworks": _values(["ens", "iso-27001"])}),
        _document("b.pdf", {"frameworks": _values(["ens"])}),
        _document("c.pdf", {}),  # eje no evaluado: cuenta como vacío
    )
    gold = GoldStandard(
        labels=[
            GoldLabel(document="a.pdf", axes={"frameworks": ["iso-27001", "ens"]}),
            GoldLabel(document="b.pdf", axes={"frameworks": ["ens", "rgpd"]}),
            GoldLabel(document="c.pdf", axes={"frameworks": ["ens"]}),
        ]
    )

    frameworks = evaluate_classification(context, gold).axes["frameworks"]

    assert frameworks.multiple is True
    assert (frameworks.accuracy, frameworks.precision, frameworks.recall) == (round(1 / 3, 4), 1.0, 0.6)
    assert {(c.label, c.assigned) for c in frameworks.confusions} == {("ens, rgpd", "ens"), ("ens", NONE_LABEL)}


def test_explicit_roots_and_windows_paths_give_the_same_keys() -> None:
    document = _document("ENS/a.pdf", {"domains": _values(["calidad"])}).model_copy(update={"source_path": "C:\\Datos\\entrada\\ENS\\a.pdf"})
    gold = GoldStandard(labels=[GoldLabel(document="ENS/a.pdf", axes={"domains": ["calidad"]})])

    report = evaluate_classification(_context(document), gold, roots=["C:\\Datos\\entrada"])

    assert report.matched == 1 and report.axes["domains"].accuracy == 1.0


def test_common_root_needs_two_paths_with_a_shared_folder() -> None:
    assert common_root(["/a/b/x.pdf"]) is None
    assert common_root(["/a/b/x.pdf", "/a/c/y.pdf"]) == "/a"
    assert common_root(["a/x.pdf", "b/y.pdf"]) is None


def test_load_gold_xlsx_reads_the_baseline_sheet(tmp_path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Referencia"
    sheet.append(["id", "documento", "dominio_ok", "tipo_ok", "marcos_ok", "notas"])
    sheet.append([1, "'=ENS/a.pdf", "calidad", None, "ens; iso-27001", "revisado"])
    sheet.append([2, "ENS/b.pdf", "ninguno", "politica", None, None])
    sheet.append([3, "ENS/c.pdf", None, None, None, "sin etiquetar"])
    sheet.append([4, None, "calidad", None, None, None])
    path = tmp_path / "referencia.xlsx"
    workbook.save(path)

    gold = load_gold_xlsx(path, columns={"domains": "dominio_ok", "material_types": "tipo_ok", "frameworks": "marcos_ok", "x": "no_existe"})

    assert [(label.document, label.axes) for label in gold.labels] == [
        ("=ENS/a.pdf", {"domains": ["calidad"], "frameworks": ["ens", "iso-27001"]}),
        ("ENS/b.pdf", {"domains": [], "material_types": ["politica"]}),
    ]
    assert [label.document for label in load_gold_xlsx(path).labels] == ["=ENS/a.pdf", "ENS/b.pdf"]


@pytest.mark.parametrize(("sheet", "column", "message"), [("Otra", "documento", "hoja"), ("Referencia", "doc", "columna")])
def test_load_gold_xlsx_explains_a_wrong_sheet_or_column(tmp_path, sheet, column, message) -> None:
    workbook = Workbook()
    workbook.active.title = "Referencia"
    workbook.active.append(["documento", "dominio_ok"])
    path = tmp_path / "r.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match=message):
        load_gold_xlsx(path, sheet=sheet, document_column=column)


def test_report_markdown_and_json_round_trip() -> None:
    report = EvaluationReport(axes={"domains": AxisEvaluation(axis="domains", labelled=1, accuracy=1.0, coverage=1.0, precision=1.0, recall=1.0)})

    assert "| domains | 1 | 1.0 | 1.0 | 1.0 | 1.0 |" in report.to_markdown()
    assert EvaluationReport.model_validate_json(report.model_dump_json()) == report
