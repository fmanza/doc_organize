"""Salidas por ejes (M1, A4): una página del sitio por eje que solo etiqueta y Excel de los documentos del contexto."""

import importlib.util
import io
import tomllib

from datetime import UTC, datetime

import pytest

from doc_organize import write_context_documents_xlsx
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.exceptions import OperationCancelledError
from doc_organize.core.models import (
    AxisValue,
    Context,
    DocumentClassification,
    DocumentVersionGroup,
    Domain,
    DomainDocument,
    Project,
    TaxonomyAxis,
    TaxonomyEntry,
    UnclassifiedDocument,
)
from doc_organize.core.progress import CancelToken

openpyxl = pytest.importorskip("openpyxl")

FRAMEWORKS = TaxonomyAxis(
    key="normative_frameworks",
    name="Marcos <b>normativos</b>",
    description="Normas que aplica el documento",
    multiple=True,
    entries=[TaxonomyEntry(slug="ens", name="ENS"), TaxonomyEntry(slug="iso-27001", name="ISO/IEC 27001"), TaxonomyEntry(slug="rgpd", name="RGPD")],
)
DOMAINS = TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=[TaxonomyEntry(slug="calidad", name="Calidad")])
MATERIALS = TaxonomyAxis(key="material_types", name="Tipos", organizes="subfolder", entries=[TaxonomyEntry(slug="politica", name="Política")])


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _value(slug: str, name: str) -> AxisValue:
    return AxisValue(slug=slug, name=name, confidence=0.8, classified_by="rules")


def _document(tmp_path, stem: str, title: str, frameworks: list[AxisValue]) -> DomainDocument:
    for suffix in (".pdf", ".json"):
        (tmp_path / f"{stem}{suffix}").write_bytes(b"{}")
    (tmp_path / f"{stem}.md").write_text(f"# {stem}\n", encoding="utf-8")
    return DomainDocument(
        source_path=str(tmp_path / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md"),
        json_path=str(tmp_path / f"{stem}.json"),
        title=title,
        document_type="pdf",
        material_type="politica",
        material_type_name="Política",
        confidence=0.9,
        classification=DocumentClassification(
            axes={"domains": [_value("calidad", "Calidad")], "material_types": [_value("politica", "Política")], "normative_frameworks": frameworks}
        ),
    )


def _context(tmp_path, *, axes: list[TaxonomyAxis] | None = None) -> Context:
    documents = [
        _document(tmp_path, "soa", "Declaración [SoA] | ENS", [_value("ens", "ENS"), _value("iso-27001", "ISO/IEC 27001")]),
        _document(tmp_path, "clave", "Acceso con password: Secreto123", [_value("ens", "ENS")]),
        _document(tmp_path, "otro", "Sin marcos", []),
    ]
    return Context(
        schema_version=2,
        project_name="Demo",
        taxonomy_manifest_used=True,
        taxonomy_axes=[DOMAINS, MATERIALS, FRAMEWORKS] if axes is None else axes,
        domains=[Domain(slug="calidad", name="Calidad", documents=documents)],
        unclassified_details=[UnclassifiedDocument(source_path=str(tmp_path / "roto.pdf"), document_type="pdf", reason="incomplete_artifacts")],
        unclassified_documents=[str(tmp_path / "roto.pdf")],
        created_at="a",
        updated_at="b",
    )


# --- Sitio -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_has_one_page_per_tag_axis_with_counts_and_links(tmp_path) -> None:
    project, context = _project(tmp_path), _context(tmp_path)
    await Reorganizer().reorganize(project, context)

    result = await SiteGenerator().generate(project, context, build=False)

    page = (tmp_path / "organizado" / "eje-normative_frameworks.md").read_text(encoding="utf-8")
    assert page.startswith("# Marcos &lt;b&gt;normativos&lt;/b&gt;".replace("&lt;", "＜").replace("&gt;", "＞"))
    assert "| ENS | 2 |" in page and "| ISO/IEC 27001 | 1 |" in page and "| RGPD | 0 |" in page
    assert "## ENS (2)" in page and "## RGPD" not in page
    assert r"- [Declaración \[SoA\] \| ENS](<calidad/politica/" in page  # corchetes y barra escapados en el enlace
    assert "Secreto123" not in page  # títulos redactados, como en el nav
    nav = tomllib.loads((tmp_path / "zensical.toml").read_text(encoding="utf-8"))["project"]["nav"]
    assert nav[-1] == {"Ejes de clasificación": [{"Marcos ＜b＞normativos＜/b＞": "eje-normative_frameworks.md"}]}
    index = result.index_path.read_text(encoding="utf-8")
    assert "## Ejes de clasificación" in index and "(eje-normative_frameworks.md) (2 documento(s) con algún valor)" in index
    # Ningún eje organizador tiene página: dominio y tipo ya son el nav.
    assert sorted(path.name for path in (tmp_path / "organizado").glob("eje-*.md")) == ["eje-normative_frameworks.md"]


@pytest.mark.asyncio
async def test_without_tag_axes_the_site_is_the_one_of_1_x_and_stale_axis_pages_go(tmp_path) -> None:
    project = _project(tmp_path)
    context = _context(tmp_path)
    await Reorganizer().reorganize(project, context)
    await SiteGenerator().generate(project, context, build=False)

    plain = _context(tmp_path, axes=[DOMAINS, MATERIALS])
    await SiteGenerator().generate(project, plain, build=False)

    assert not list((tmp_path / "organizado").glob("eje-*.md"))
    nav = tomllib.loads((tmp_path / "zensical.toml").read_text(encoding="utf-8"))["project"]["nav"]
    assert [next(iter(item)) for item in nav] == ["Inicio", "Calidad"]
    assert "Ejes" not in (tmp_path / "organizado" / "index.md").read_text(encoding="utf-8")


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(importlib.util.find_spec("zensical") is None, reason="zensical no instalado (extra site)")
async def test_real_build_renders_the_axis_page_with_working_links(tmp_path) -> None:
    project, context = _project(tmp_path), _context(tmp_path)
    await Reorganizer().reorganize(project, context)

    await SiteGenerator().generate(project, context, timeout=120)

    html = (tmp_path / "site" / "eje-normative_frameworks" / "index.html").read_text(encoding="utf-8")
    assert "<b>normativos</b>" not in html
    assert 'href="../calidad/politica/' in html


# --- Excel -----------------------------------------------------------------------------------------------------------


def test_excel_has_a_column_per_tag_axis_and_counts_per_value(tmp_path) -> None:
    buffer = io.BytesIO()

    written = write_context_documents_xlsx(buffer, _context(tmp_path))

    workbook = openpyxl.load_workbook(buffer)
    documents = list(workbook["Documentos"].iter_rows(values_only=True))
    axes = list(workbook["Ejes"].iter_rows(values_only=True))
    values = list(workbook["Valores"].iter_rows(values_only=True))
    assert written == len(documents) - 1 + len(axes) - 1 + len(values) - 1 == 4 + 5 + 9
    header = documents[0]
    assert header[-1] == "Marcos <b>normativos</b>"
    rows = {row[0]: dict(zip(header, row, strict=True)) for row in documents[1:]}
    assert rows["soa.pdf"]["Marcos <b>normativos</b>"] == "ENS; ISO/IEC 27001"
    assert rows["soa.pdf"]["Dominio"] == "calidad" and rows["soa.pdf"]["Estado"] == "Clasificado"
    assert rows["otro.pdf"]["Marcos <b>normativos</b>"] in ("", None)
    assert rows["roto.pdf"]["Estado"] == "Sin clasificar: conversión incompleta"
    counts = {(row[0], row[3]): row[5] for row in axes[1:]}
    assert counts == {
        ("domains", "calidad"): 3,
        ("material_types", "politica"): 3,
        ("normative_frameworks", "ens"): 2,
        ("normative_frameworks", "iso-27001"): 1,
        ("normative_frameworks", "rgpd"): 0,
    }


def test_excel_neutralizes_formulas_in_titles_and_axis_names(tmp_path) -> None:
    context = _context(tmp_path, axes=[DOMAINS, MATERIALS, FRAMEWORKS.model_copy(update={"name": "=HYPERLINK(1)"})])
    context.domains[0].documents[0].title = "=cmd|'/c calc'!A1"
    buffer = io.BytesIO()

    write_context_documents_xlsx(buffer, context)

    sheet = openpyxl.load_workbook(buffer)["Documentos"]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][-1] == "'=HYPERLINK(1)"
    assert rows[1][3] == "'=cmd|'/c calc'!A1"


def test_cancelled_excel_leaves_no_partial_file(tmp_path) -> None:
    token = CancelToken()
    token.cancel()
    destination = tmp_path / "contexto.xlsx"

    with pytest.raises(OperationCancelledError):
        write_context_documents_xlsx(destination, _context(tmp_path), cancel_token=token)

    assert not destination.exists()


def test_excel_values_sheet_has_who_classified_each_axis_value(tmp_path) -> None:
    """Petición de la web (W8): quién asignó cada valor de cada eje, con su confianza y su cita."""
    context = _context(tmp_path)
    soa = context.domains[0].documents[0]
    soa.classification.axes["normative_frameworks"][1] = AxisValue(
        slug="iso-27001", name="ISO/IEC 27001", confidence=0.7, classified_by="ai", evidence="=según ISO 27001", evidence_verified=True
    )
    buffer = io.BytesIO()

    write_context_documents_xlsx(buffer, context)

    rows = list(openpyxl.load_workbook(buffer)["Valores"].iter_rows(values_only=True))
    assert rows[0] == ("Ruta completa", "Eje", "Valor", "Nombre del valor", "Clasificado por", "Confianza", "Evidencia", "Evidencia verificada")
    by_value = {(row[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1], row[1], row[2]): row[4:] for row in rows[1:]}
    assert by_value[("soa.pdf", "normative_frameworks", "iso-27001")] == ("ai", 0.7, "'=según ISO 27001", "Sí")
    assert by_value[("soa.pdf", "domains", "calidad")] == ("rules", 0.8, None, None)


def test_excel_with_roots_writes_relative_keys_and_versions(tmp_path) -> None:
    """Peticiones de la web (W8): `roots=` como `write_ai_context_bundle`, y las versiones de cada documento."""
    context = _context(tmp_path)
    soa, clave = (str(tmp_path / "soa.pdf"), str(tmp_path / "clave.pdf"))
    context.version_groups = [DocumentVersionGroup(key="soa.pdf", members=[clave, soa], versions=["1", "2"], current=soa)]
    buffer = io.BytesIO()

    write_context_documents_xlsx(buffer, context, roots=[str(tmp_path)])

    workbook = openpyxl.load_workbook(buffer)
    cells = [str(cell) for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True) for cell in row if cell is not None]
    assert not any(str(tmp_path) in cell for cell in cells)  # ninguna ruta absoluta
    documents = list(workbook["Documentos"].iter_rows(values_only=True))
    rows = {row[0]: dict(zip(documents[0], row, strict=True)) for row in documents[1:]}
    assert rows["soa.pdf"]["Ruta completa"] == "soa.pdf" and rows["soa.pdf"]["Carpeta"] in ("", None)
    assert (rows["soa.pdf"]["Grupo de versiones"], rows["soa.pdf"]["Versión"], rows["soa.pdf"]["Vigente"]) == ("soa.pdf", "2", "Sí")
    assert (rows["clave.pdf"]["Versión"], rows["clave.pdf"]["Vigente"]) == ("1", "No")
    assert rows["otro.pdf"]["Grupo de versiones"] in ("", None)
    assert {row[0] for row in list(workbook["Valores"].iter_rows(values_only=True))[1:]} == {"soa.pdf", "clave.pdf", "otro.pdf"}
