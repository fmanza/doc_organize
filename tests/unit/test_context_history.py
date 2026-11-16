"""Historial de construcciones del contexto (1.5.0): qué documentos entran, salen o cambian, y su exportación a XLSX."""

import json
import logging

from datetime import UTC, datetime
from pathlib import Path

import openpyxl
import pytest

from doc_organize.context import context_builder as context_builder_module
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_history import build_record, diff_contexts, list_context_builds
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.core.exceptions import InvalidPathError
from doc_organize.core.models import Context, ContextBuildRecord, ContextChange, ConversionResult, Domain, DomainDocument, Project
from doc_organize.export import load_context_history, write_context_history_xlsx
from doc_organize.main import main
from doc_organize.projects import ProjectLayout
from doc_organize.projects.layout import validate_output_folder_name


def _document(path: str, material_type: str | None = None, classified_by: str = "rules") -> DomainDocument:
    return DomainDocument(
        source_path=path,
        markdown_path=f"{path}.md",
        json_path=f"{path}.json",
        title=Path(path).stem,
        document_type="pdf",
        confidence=1.0,
        material_type=material_type,
        classified_by=classified_by,
    )


def _context(domains: dict[str, list[DomainDocument]], unclassified: list[str] = (), updated_at: str = "t2") -> Context:  # type: ignore[assignment]
    return Context(
        project_name="P",
        domains=[Domain(slug=slug, name=slug, documents=documents) for slug, documents in domains.items()],
        unclassified_documents=list(unclassified),
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_first_build_adds_every_document() -> None:
    current = _context({"calidad": [_document("/a.pdf")]}, unclassified=["/b.pdf"])

    changes = diff_contexts(None, current)

    assert [(c.source_path, c.change, c.domain, c.classified_by) for c in changes] == [
        ("/a.pdf", "added", "calidad", "rules"),
        ("/b.pdf", "added", None, None),
    ]


def test_changes_between_builds() -> None:
    previous = _context(
        {
            "calidad": [_document("/mueve.pdf"), _document("/igual.pdf"), _document("/sale.pdf"), _document("/a-sin.pdf")],
            "auditoria": [_document("/tipo.pdf", material_type="normativa"), _document("/quien.pdf")],
        },
        unclassified=["/clasifica.pdf"],
        updated_at="t1",
    )
    current = _context(
        {
            "calidad": [_document("/igual.pdf"), _document("/clasifica.pdf", classified_by="ai")],
            "auditoria": [
                _document("/mueve.pdf"),
                _document("/tipo.pdf", material_type="procedimiento"),
                _document("/quien.pdf", classified_by="ai"),  # mismo sitio, otro decisor: no es un cambio
                _document("/nuevo.pdf"),
            ],
        },
        unclassified=["/a-sin.pdf"],
    )

    changes = {change.source_path: change for change in diff_contexts(previous, current)}

    assert sorted(changes) == ["/a-sin.pdf", "/clasifica.pdf", "/mueve.pdf", "/nuevo.pdf", "/sale.pdf", "/tipo.pdf"]
    assert (changes["/mueve.pdf"].change, changes["/mueve.pdf"].previous_domain, changes["/mueve.pdf"].domain) == (
        "reclassified",
        "calidad",
        "auditoria",
    )
    assert (changes["/a-sin.pdf"].change, changes["/a-sin.pdf"].domain, changes["/a-sin.pdf"].classified_by) == ("reclassified", None, None)
    assert (changes["/clasifica.pdf"].previous_domain, changes["/clasifica.pdf"].classified_by) == (None, "ai")
    assert (changes["/tipo.pdf"].previous_material_type, changes["/tipo.pdf"].material_type) == ("normativa", "procedimiento")
    assert (changes["/sale.pdf"].change, changes["/sale.pdf"].previous_domain, changes["/sale.pdf"].domain) == ("removed", "calidad", None)
    assert changes["/nuevo.pdf"].change == "added"


def test_record_summarises_the_build() -> None:
    previous = _context({}, unclassified=["/a.pdf"], updated_at="t1")
    current = _context({"calidad": [_document("/a.pdf")]}, unclassified=["/b.pdf"])

    record = build_record(previous, current)

    assert (record.built_at, record.previous_built_at, record.classified, record.unclassified) == ("t2", "t1", 1, 1)
    assert [change.change for change in record.changes] == ["reclassified", "added"]


def test_invalid_lines_are_skipped_and_newest_comes_first(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    history = tmp_path / "CONTEXT_HISTORY.jsonl"
    first = ContextBuildRecord(built_at="2026-01-01", project_name="P", classified=0, unclassified=0)
    second = ContextBuildRecord(built_at="2026-01-02", project_name="P", classified=1, unclassified=0)
    history.write_text(f"{first.model_dump_json()}\n{{corte a medias\n\n{second.model_dump_json()}\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        records = list_context_builds(history)

    assert [record.built_at for record in records] == ["2026-01-02", "2026-01-01"]
    assert "Línea inválida" in caplog.text


# ----- ContextBuilder -----


def _project(tmp_path: Path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _converted(tmp_path: Path, folder: str, name: str) -> ConversionResult:
    source = tmp_path / "origen" / folder / name
    source.parent.mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{source.stem}.json"
    json_path.write_text(json.dumps({"title": source.stem, "chunks": []}), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(tmp_path / f"{source.stem}.md"), json_path=str(json_path), success=True)


@pytest.mark.asyncio
async def test_each_build_appends_what_changed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    builder = ContextBuilder(ContextRegistry())
    informe = _converted(tmp_path, "Calidad", "informe.pdf")
    acta = _converted(tmp_path, "Calidad", "acta.pdf")

    first = await builder.build(project, [informe, acta])
    moved = _converted(tmp_path, "Auditoria", "acta.pdf")  # la misma ruta de origen no: otra carpeta, otro documento
    second = await builder.build(project, [informe, moved])

    history = ProjectLayout.for_project(project).context_history
    newest, oldest = list_context_builds(history)
    assert (oldest.built_at, oldest.previous_built_at, len(oldest.changes)) == (first.updated_at, None, 2)
    assert newest.previous_built_at == first.updated_at
    assert newest.built_at == second.updated_at
    assert {(change.change, Path(change.source_path).parent.name) for change in newest.changes} == {("removed", "Calidad"), ("added", "Auditoria")}
    assert newest.built_with_version == second.built_with_version


@pytest.mark.asyncio
async def test_rebuilding_without_changes_records_an_empty_build(tmp_path: Path) -> None:
    project = _project(tmp_path)
    builder = ContextBuilder(ContextRegistry())
    documents = [_converted(tmp_path, "Calidad", "informe.pdf")]

    await builder.build(project, documents)
    await builder.build(project, documents)

    newest, _ = list_context_builds(ProjectLayout.for_project(project).context_history)
    assert newest.changes == []
    assert newest.classified == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("damaged", [b"{no es json", b"\xff\xfe no es UTF-8", b"[]", b'{"domains": ["no es un objeto"]}'])
async def test_unreadable_previous_context_does_not_stop_the_build(tmp_path: Path, caplog: pytest.LogCaptureFixture, damaged: bytes) -> None:
    project = _project(tmp_path)
    documents = [_converted(tmp_path, "Calidad", "informe.pdf")]
    await ContextBuilder(ContextRegistry()).build(project, documents)
    ProjectLayout.for_project(project).context_file.write_bytes(damaged)

    with caplog.at_level(logging.WARNING):
        await ContextBuilder(ContextRegistry()).build(project, documents)

    newest, _ = list_context_builds(ProjectLayout.for_project(project).context_history)
    assert newest.previous_built_at is None
    assert [change.change for change in newest.changes] == ["added"]
    assert "contexto anterior" in caplog.text


@pytest.mark.asyncio
async def test_rebuilding_keeps_created_at_and_moves_updated_at(tmp_path: Path) -> None:
    project = _project(tmp_path)
    registry = ContextRegistry()
    documents = [_converted(tmp_path, "Calidad", "informe.pdf")]
    first = await ContextBuilder(registry).build(project, documents)

    second = await ContextBuilder(registry).build(project, documents)

    assert second.created_at == first.created_at
    assert second.updated_at > first.updated_at
    assert (await registry.load_context(project)).created_at == first.created_at


@pytest.mark.asyncio
async def test_created_at_starts_again_after_deleting_the_context(tmp_path: Path) -> None:
    project = _project(tmp_path)
    registry = ContextRegistry()
    documents = [_converted(tmp_path, "Calidad", "informe.pdf")]
    first = await ContextBuilder(registry).build(project, documents)
    await registry.delete_context(project)

    second = await ContextBuilder(registry).build(project, documents)

    assert second.created_at != first.created_at
    assert second.created_at == second.updated_at


@pytest.mark.asyncio
async def test_created_at_starts_again_when_the_previous_context_is_unreadable(tmp_path: Path) -> None:
    project = _project(tmp_path)
    documents = [_converted(tmp_path, "Calidad", "informe.pdf")]
    first = await ContextBuilder(ContextRegistry()).build(project, documents)
    ProjectLayout.for_project(project).context_file.write_bytes(b"{no es json")

    second = await ContextBuilder(ContextRegistry()).build(project, documents)

    assert second.created_at != first.created_at
    assert second.created_at == second.updated_at


@pytest.mark.asyncio
async def test_history_write_failure_keeps_the_saved_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _disk_full(history_path: Path, record: ContextBuildRecord, policy: object = None) -> None:
        raise OSError("No queda espacio en el disco")

    monkeypatch.setattr(context_builder_module, "append_context_build", _disk_full)
    project = _project(tmp_path)

    with caplog.at_level(logging.WARNING):
        context = await ContextBuilder(ContextRegistry()).build(project, [_converted(tmp_path, "Calidad", "informe.pdf")])

    assert (await ContextRegistry().load_context(project)).updated_at == context.updated_at
    assert "histórico del contexto" in caplog.text


def test_history_folder_cannot_be_the_reorganized_folder() -> None:
    with pytest.raises(InvalidPathError):
        validate_output_folder_name("Historial_Contexto")


# ----- Exportación -----


def _records() -> list[ContextBuildRecord]:
    return [
        ContextBuildRecord(
            built_at="2026-11-02T00:00:00+00:00",
            previous_built_at="2026-11-01T00:00:00+00:00",
            project_name='=HYPERLINK("x")',
            built_with_version="1.5.0",
            ai_classification_model="clasificador",
            classified=1,
            unclassified=1,
            changes=[
                ContextChange(source_path="/docs/=cmd.pdf", change="reclassified", previous_domain="calidad", domain=None),
                ContextChange(source_path="/docs/nuevo.pdf", change="added", domain="auditoria", classified_by="ai"),
            ],
        ),
        ContextBuildRecord(built_at="2026-11-01T00:00:00+00:00", project_name="P", classified=0, unclassified=1),
    ]


def test_context_history_xlsx_has_builds_and_changes(tmp_path: Path) -> None:
    destination = tmp_path / "historial.xlsx"

    assert write_context_history_xlsx(destination, _records()) == 4  # 2 construcciones + 2 cambios

    workbook = openpyxl.load_workbook(destination)
    builds = list(workbook["Construcciones"].iter_rows(values_only=True))
    changes = list(workbook["Cambios"].iter_rows(values_only=True))
    assert builds[1][:3] == ("2026-11-02T00:00:00+00:00", "2026-11-01T00:00:00+00:00", '\'=HYPERLINK("x")')
    assert builds[1][5:] == ("clasificador", None, 1, 1, 2)
    assert changes[1][1] == "'=cmd.pdf"  # protegido contra la inyección de fórmulas
    assert changes[1][4:7] == ("Cambia", "calidad", "(sin clasificar)")
    assert changes[2][4:7] == ("Entra", None, "auditoria")
    assert changes[2][9] == "ai"


def test_cli_exports_the_project_context_history(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    layout.context_history.parent.mkdir(parents=True)
    layout.context_history.write_text("".join(f"{record.model_dump_json()}\n" for record in reversed(_records())), encoding="utf-8")
    destination = tmp_path / "historial.xlsx"

    assert main(["export", "context-xlsx", "--output-root", str(tmp_path), "-o", str(destination)]) == 0

    assert [row[0] for row in openpyxl.load_workbook(destination)["Construcciones"].iter_rows(min_row=2, values_only=True)] == [
        "2026-11-02T00:00:00+00:00",
        "2026-11-01T00:00:00+00:00",
    ]
    assert load_context_history([layout.context_history, tmp_path / "no-existe.jsonl"])[0].classified == 1
