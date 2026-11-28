"""`scripts/benchmark/run.py` (2.6.0, E3 del PLAN de F0): las piezas que no necesitan un proyecto real.

El script no se empaqueta; se carga desde su ruta. Lo que se prueba aquí es lo que decide la validez de una medición
(partición fija y disjunta, kappa, ablaciones que se deshacen, salida fuera del repositorio), no la construcción en seco,
que ya prueba `test_dry_run.py`.
"""

import importlib.util
import sys

from pathlib import Path
from types import ModuleType

import pytest

from openpyxl import Workbook, load_workbook

from doc_organize import GoldLabel, GoldStandard
from doc_organize.context import domain_classifier
from doc_organize.core.models import Context, ConversionResult, Domain, DomainDocument, UnclassifiedDocument

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark" / "run.py"


@pytest.fixture(scope="module")
def bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark_run", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_run"] = module
    spec.loader.exec_module(module)
    return module


def _gold(values: dict[str, str]) -> GoldStandard:
    return GoldStandard(labels=[GoldLabel(document=key, axes={"domains": [value]}) for key, value in values.items()])


def test_out_inside_the_repository_is_rejected(bench: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="fuera"):
        bench._safe_out(SCRIPT.parent / "out")

    assert bench._safe_out(tmp_path / "informes").is_dir()


def test_split_is_stratified_disjoint_and_reproducible(bench: ModuleType) -> None:
    gold = _gold({f"a{i}.pdf": "calidad" for i in range(9)} | {f"b{i}.pdf": "riesgos" for i in range(6)})

    split = bench._stratified_split(gold, "domains", holdout=1 / 3, folds=5, seed=3)

    locked, rest = set(split["holdout"]), set(split["calibrate"])
    assert not locked & rest and len(locked | rest) == 15
    assert sum(key.startswith("a") for key in locked) == 3 and sum(key.startswith("b") for key in locked) == 2
    assert set(split["folds"]) == rest and set(split["folds"].values()) == set(range(5))
    assert bench._stratified_split(gold, "domains", holdout=1 / 3, folds=5, seed=3) == split


def test_saved_partition_is_reused(bench: ModuleType, tmp_path: Path) -> None:
    gold = _gold({f"d{i}.pdf": "calidad" for i in range(6)})

    first = bench._partition(gold, tmp_path, "domains", seed=1)
    again = bench._partition(gold, tmp_path, "domains", seed=99)  # otra semilla: manda la guardada

    assert again == first


def test_saved_partition_refuses_a_grown_reference(bench: ModuleType, tmp_path: Path) -> None:
    """Filas añadidas a la referencia después de partir no pueden quedar fuera de los dos tramos sin avisar."""
    bench._partition(_gold({f"d{i}.pdf": "calidad" for i in range(6)}), tmp_path, "domains", seed=1)

    with pytest.raises(SystemExit, match="no están en la partición"):
        bench._partition(_gold({f"d{i}.pdf": "calidad" for i in range(7)}), tmp_path, "domains", seed=1)


@pytest.mark.parametrize("bad", [["--path-map", "/mnt/documentation"], ["--column", "domains"]])
def test_malformed_mappings_are_rejected(bench: ModuleType, tmp_path: Path, bad: list[str]) -> None:
    base = ["run", "--project-root", str(tmp_path), "--gold", str(tmp_path / "r.xlsx"), "--config", "c.toml", "--out", str(tmp_path / "o")]

    with pytest.raises(SystemExit):
        bench.main(base + bad)


def test_cohen_kappa(bench: ModuleType) -> None:
    assert bench._cohen_kappa([("a", "a"), ("b", "b")]) == 1.0
    # acuerdo observado 0,5 y esperado 0,5 → kappa 0
    assert bench._cohen_kappa([("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]) == 0.0
    assert bench._cohen_kappa([]) is None


def test_ablations_change_the_scorer_only_inside_the_block(bench: ModuleType) -> None:
    original = domain_classifier.score_catalog
    text = "leyenda del plano"

    assert original(["legal"], text, "", {"legal": ["ley"]}) == ("legal", 0.5)
    with bench._ablated(["whole_word"], 2.0):
        assert domain_classifier.score_catalog(["legal"], text, "", {"legal": ["ley"]}) == (None, 0.0)
    with bench._ablated(["tie_abstain"], 2.0):
        assert domain_classifier.score_catalog(["riesgos", "continuidad"], "riesgos y continuidad", "") == (None, 1.0)
    with bench._ablated(["no_divide"], 2.0):
        assert domain_classifier.score_catalog(["incidencia"], "incidente", "", {"incidencia": ["incidente", "brecha", "csirt", "evidencia"]}) == (
            "incidencia",
            0.5,
        )

    assert domain_classifier.score_catalog is original


def test_blind_sheet_hides_assignments_and_agreement_reads_it_back(bench: ModuleType, tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Referencia"
    sheet.append(["documento", "dominio_doc_organize", "dominio_ok", "tipo_ok", "notas"])
    for i in range(6):
        sheet.append([f"'d{i}.pdf", "riesgos", "calidad" if i % 2 else "riesgos", "manual", None])
    reference = tmp_path / "referencia.xlsx"
    workbook.save(reference)

    bench.main(["blind-sheet", "--gold", str(reference), "--size", "4", "--out", str(tmp_path / "salida")])

    blind_path = tmp_path / "salida" / "hoja_a_ciegas.xlsx"
    blind = load_workbook(blind_path)
    rows = list(blind["A ciegas"].iter_rows(values_only=True))
    assert rows[0] == ("id", "documento", "tipo_fichero", "dominio_ok", "tipo_ok", "notas")
    assert len(rows) == 5 and all(row[3] is None and row[4] is None for row in rows[1:])
    for row in blind["A ciegas"].iter_rows(min_row=2):
        row[3].value, row[4].value = "riesgos", "manual"  # una persona etiqueta todo como «riesgos»
    blind.save(blind_path)

    bench.main(["agreement", "--gold", str(reference), "--blind", str(blind_path), "--out", str(tmp_path / "salida")])

    report = (tmp_path / "salida" / "acuerdo.md").read_text(encoding="utf-8")
    assert "| domains | 4 |" in report and "| material_types | 4 | 1.0 | 1.0 |" in report
    assert "## Discrepancias" in report


@pytest.mark.parametrize("config", sorted((SCRIPT.parent / "configs").glob("*.toml")), ids=lambda path: path.stem)
def test_example_configs_load_and_point_to_a_template(bench: ModuleType, config: Path) -> None:
    loaded = bench._load_config(config)

    assert loaded["template"].is_file()
    assert set(loaded["ablation"]) <= set(bench.ABLATIONS)


def _built(classified: int, sent: int) -> Context:
    documents = [
        DomainDocument(source_path=f"/mnt/e/ENS/d{i}.pdf", markdown_path="x.md", json_path="x.json", title="t", document_type="pdf", confidence=0.5)
        for i in range(classified)
    ]
    context = Context(
        project_name="p",
        created_at="2026-11-28T00:00:00+00:00",
        updated_at="2026-11-28T00:00:00+00:00",
        domains=[Domain(slug="calidad", name="Calidad", documents=documents)] if documents else [],
    )
    context.ai_stats.classification.sent = sent
    return context


def _requested(count: int) -> list[ConversionResult]:
    return [ConversionResult(source_path=f"/mnt/e/ENS/d{i}.pdf", json_path="x.json", success=True) for i in range(count)]


def test_scan_roots_use_the_whole_saved_context_not_the_subset(bench: ModuleType) -> None:
    """Todos los documentos del tramo en una subcarpeta: su carpeta común sería `/mnt/e/ENS` y las claves no casarían."""
    every = ["/mnt/e/ENS/a.pdf", "/mnt/e/ISO/b.pdf"]

    assert bench._scan_roots(every, []) == ["/mnt/e"]
    assert bench._scan_roots(every, ["/mnt"]) == ["/mnt"]
    assert bench._scan_roots(["/mnt/e/ENS/a.pdf"], []) is None


def test_a_dry_run_missing_documents_is_not_measured(bench: ModuleType) -> None:
    assert bench._incomplete(_built(3, 0), _requested(3), ai_all=False) is None
    assert "solo tiene 0 de 3" in bench._incomplete(_built(0, 0), _requested(3), ai_all=False)


def test_ai_all_with_nothing_classified_is_not_a_pass(bench: ModuleType) -> None:
    """Antes «enviados = clasificados» pasaba con 0 = 0."""
    assert bench._incomplete(_built(3, 3), _requested(3), ai_all=True) is None
    assert "no llegó a todos" in bench._incomplete(_built(3, 2), _requested(3), ai_all=True)
    empty = _built(0, 0)
    empty.unclassified_details = [
        UnclassifiedDocument(source_path=f"/mnt/e/ENS/d{i}.pdf", document_type="pdf", reason="below_threshold") for i in range(3)
    ]
    assert "no llegó a todos" in bench._incomplete(empty, _requested(3), ai_all=True)


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"ai_all": True}, (True, 0.5, "all")),
        ({"ai_all": True, "threshold": 0.6}, (True, 0.6, "all")),
        ({"ai_all_legacy": True}, (True, 1.01, "unclassified")),
        ({"ai_scope": "missing_axes"}, (False, 0.5, "missing_axes")),
        ({}, (False, 0.5, "off")),
    ],
)
def test_ai_all_uses_the_real_scope_and_the_trick_only_on_request(bench: ModuleType, config: dict, expected: tuple) -> None:
    assert bench._scope(config) == expected


def test_strata_missing_from_the_saved_context_are_reported(bench: ModuleType) -> None:
    """La reponderación solo vale con el contexto del que se sacó la muestra: si sus estratos no están, se avisa."""
    from collections import Counter

    rows = [{"documento": "a.pdf", "dominio_doc_organize": "riesgos"}, {"documento": "b.pdf", "dominio_doc_organize": None}]

    assert bench._missing_strata(rows, Counter({"riesgos": 10, "sin-clasificar": 3}), "dominio_doc_organize") == []
    assert bench._missing_strata(rows, Counter({"calidad": 10}), "dominio_doc_organize") == ["riesgos", "sin-clasificar"]
