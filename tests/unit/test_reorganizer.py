"""Tests de Reorganizer (copia física de documentos clasificados)."""

from datetime import UTC, datetime

import pytest

from doc_organize.context.mkdocs_generator import MkDocsGenerator
from doc_organize.context.reorganizer import Reorganizer, resolve_document_slug_parts
from doc_organize.core.exceptions import IncompleteConversionArtifactsError
from doc_organize.core.models import Context, Domain, DomainDocument, Project


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _make_context(project: Project, domains: list[Domain]) -> Context:
    now = datetime.now(UTC).isoformat()
    return Context(project_name=project.name, domains=domains, created_at=now, updated_at=now)


@pytest.mark.asyncio
async def test_reorganize_copies_all_three_artifacts(tmp_path):
    project = _make_project(tmp_path)
    source_dir = tmp_path / "originales"
    source_dir.mkdir()
    source = source_dir / "informe.pdf"
    source.write_bytes(b"%PDF-1.4 contenido")
    markdown = tmp_path / "informe.md"
    markdown.write_text("# Informe", encoding="utf-8")
    json_file = tmp_path / "informe.json"
    json_file.write_text('{"title": "Informe"}', encoding="utf-8")

    document = DomainDocument(
        source_path=str(source),
        markdown_path=str(markdown),
        json_path=str(json_file),
        title="Informe",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])

    output_root = await Reorganizer().reorganize(project, context)

    target_dir = output_root / "calidad" / "pdf" / "informe"
    assert (target_dir / "informe.pdf").read_bytes() == b"%PDF-1.4 contenido"
    assert (target_dir / "informe.md").read_text(encoding="utf-8") == "# Informe"
    assert (target_dir / "informe.json").read_text(encoding="utf-8") == '{"title": "Informe"}'
    assert source.exists()  # copia, no mueve


@pytest.mark.asyncio
async def test_reorganize_raises_when_artifact_missing(tmp_path):
    project = _make_project(tmp_path)
    document = DomainDocument(
        source_path=str(tmp_path / "no_existe.pdf"),
        markdown_path=str(tmp_path / "no_existe.md"),
        json_path=str(tmp_path / "no_existe.json"),
        title="No existe",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])

    with pytest.raises(IncompleteConversionArtifactsError):
        await Reorganizer().reorganize(project, context)


@pytest.mark.asyncio
async def test_rebuild_removes_stale_copies_of_a_domain_no_longer_present(tmp_path):
    project = _make_project(tmp_path)
    reorganizer = Reorganizer()

    doc_a = DomainDocument(
        source_path=str(_write_file(tmp_path, "a.pdf", b"A")),
        markdown_path=str(_write_file(tmp_path, "a.md", b"# A")),
        json_path=str(_write_file(tmp_path, "a.json", b"{}")),
        title="A",
        document_type="pdf",
        confidence=0.9,
    )
    context_v1 = _make_context(project, [Domain(slug="ciberseguridad", name="Ciberseguridad", documents=[doc_a])])
    output_root = await reorganizer.reorganize(project, context_v1)
    assert (output_root / "ciberseguridad" / "pdf" / "a").is_dir()

    doc_b = DomainDocument(
        source_path=str(_write_file(tmp_path, "b.pdf", b"B")),
        markdown_path=str(_write_file(tmp_path, "b.md", b"# B")),
        json_path=str(_write_file(tmp_path, "b.json", b"{}")),
        title="B",
        document_type="pdf",
        confidence=0.9,
    )
    context_v2 = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[doc_b])])
    await reorganizer.reorganize(project, context_v2)

    assert not (output_root / "ciberseguridad").exists()
    assert (output_root / "calidad" / "pdf" / "b").is_dir()


@pytest.mark.asyncio
async def test_rebuild_removes_document_dropped_from_a_domain_that_stays(tmp_path):
    project = _make_project(tmp_path)
    reorganizer = Reorganizer()

    doc_a = DomainDocument(
        source_path=str(_write_file(tmp_path, "a.pdf", b"A")),
        markdown_path=str(_write_file(tmp_path, "a.md", b"# A")),
        json_path=str(_write_file(tmp_path, "a.json", b"{}")),
        title="A",
        document_type="pdf",
        confidence=0.9,
    )
    doc_c = DomainDocument(
        source_path=str(_write_file(tmp_path, "c.pdf", b"C")),
        markdown_path=str(_write_file(tmp_path, "c.md", b"# C")),
        json_path=str(_write_file(tmp_path, "c.json", b"{}")),
        title="C",
        document_type="pdf",
        confidence=0.9,
    )
    output_root = await reorganizer.reorganize(project, _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[doc_a, doc_c])]))
    assert (output_root / "calidad" / "pdf" / "a").is_dir()
    assert (output_root / "calidad" / "pdf" / "c").is_dir()

    # Reconstrucción: el dominio "calidad" sigue existiendo, pero ahora solo con doc_c.
    await reorganizer.reorganize(project, _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[doc_c])]))

    assert not (output_root / "calidad" / "pdf" / "a").exists()
    assert (output_root / "calidad" / "pdf" / "c").is_dir()


def _write_file(tmp_path, name: str, content: bytes):
    path = tmp_path / name
    path.write_bytes(content)
    return path


@pytest.mark.asyncio
async def test_failed_rebuild_does_not_destroy_previously_valid_copies(tmp_path):
    """Si un documento nuevo del lote tiene un artefacto ausente, la reconstrucción
    debe fallar SIN haber borrado las copias válidas de una reconstrucción anterior
    del mismo dominio (AUDIT_CODE, sesión 2026-09-09 — antes `_reset_domain_dir`
    borraba la carpeta del dominio antes de descubrir el fallo)."""
    project = _make_project(tmp_path)
    reorganizer = Reorganizer()

    doc_a = DomainDocument(
        source_path=str(_write_file(tmp_path, "a.pdf", b"A")),
        markdown_path=str(_write_file(tmp_path, "a.md", b"# A")),
        json_path=str(_write_file(tmp_path, "a.json", b"{}")),
        title="A",
        document_type="pdf",
        confidence=0.9,
    )
    output_root = await reorganizer.reorganize(project, _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[doc_a])]))
    assert (output_root / "calidad" / "pdf" / "a" / "a.pdf").read_bytes() == b"A"

    doc_broken = DomainDocument(
        source_path=str(tmp_path / "no_existe.pdf"),
        markdown_path=str(tmp_path / "no_existe.md"),
        json_path=str(tmp_path / "no_existe.json"),
        title="Roto",
        document_type="pdf",
        confidence=0.9,
    )
    with pytest.raises(IncompleteConversionArtifactsError):
        await reorganizer.reorganize(project, _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[doc_a, doc_broken])]))

    # La copia de doc_a de la reconstrucción anterior sigue intacta: la validación
    # se hizo antes de borrar nada.
    assert (output_root / "calidad" / "pdf" / "a" / "a.pdf").read_bytes() == b"A"


def test_resolve_document_slug_parts_uses_document_type_and_markdown_stem():
    document = DomainDocument(
        source_path="/docs/x.pdf", markdown_path="/out/informe.md", json_path="/out/informe.json", title="X", document_type="pdf", confidence=0.9
    )

    document_type, stem = resolve_document_slug_parts(document)

    assert document_type == "pdf"
    assert stem == "informe"


@pytest.mark.asyncio
async def test_reorganizer_destination_matches_mkdocs_generator_nav_path(tmp_path, monkeypatch):
    """`Reorganizer` (destino real en disco) y `MkDocsGenerator` (ruta en el `nav`
    de `mkdocs.yml`) deben coincidir para el mismo documento — antes cada uno
    calculaba la misma fórmula por separado, sin nada que lo garantizara
    (AUDIT_CODE, sesión 2026-09-09)."""
    monkeypatch.setattr("doc_organize.context.mkdocs_generator.shutil.which", lambda _name: None)
    project = _make_project(tmp_path)
    document = DomainDocument(
        source_path=str(_write_file(tmp_path, "informe.pdf", b"X")),
        markdown_path=str(_write_file(tmp_path, "informe.md", b"# X")),
        json_path=str(_write_file(tmp_path, "informe.json", b"{}")),
        title="Informe",
        document_type="pdf",
        confidence=0.9,
    )
    domain = Domain(slug="calidad", name="Calidad", documents=[document])
    context = _make_context(project, [domain])

    output_root = await Reorganizer().reorganize(project, context)
    await MkDocsGenerator().generate(project, context)

    mkdocs_yml = (tmp_path / "mkdocs.yml").read_text(encoding="utf-8")
    nav_relative_path = "calidad/pdf/informe/informe.md"
    assert nav_relative_path in mkdocs_yml

    disk_path = output_root / nav_relative_path
    assert disk_path.is_file()


@pytest.mark.asyncio
async def test_on_document_copied_called_once_per_document_in_order(tmp_path):
    project = _make_project(tmp_path)
    doc_a = DomainDocument(
        source_path=str(_write_file(tmp_path, "a.pdf", b"A")),
        markdown_path=str(_write_file(tmp_path, "a.md", b"# A")),
        json_path=str(_write_file(tmp_path, "a.json", b"{}")),
        title="A",
        document_type="pdf",
        confidence=0.9,
    )
    doc_b = DomainDocument(
        source_path=str(_write_file(tmp_path, "b.pdf", b"B")),
        markdown_path=str(_write_file(tmp_path, "b.md", b"# B")),
        json_path=str(_write_file(tmp_path, "b.json", b"{}")),
        title="B",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[doc_a, doc_b])])

    progress_calls: list[tuple[int, int, str]] = []

    async def on_document_copied(index: int, total: int, path: str) -> None:
        progress_calls.append((index, total, path))

    await Reorganizer().reorganize(project, context, on_document_copied=on_document_copied)

    assert progress_calls == [(1, 2, doc_a.source_path), (2, 2, doc_b.source_path)]


@pytest.mark.asyncio
async def test_on_document_copied_not_called_when_no_documents(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    progress_calls: list[tuple[int, int, str]] = []

    async def on_document_copied(index: int, total: int, path: str) -> None:
        progress_calls.append((index, total, path))

    await Reorganizer().reorganize(project, context, on_document_copied=on_document_copied)

    assert progress_calls == []


@pytest.mark.asyncio
async def test_delete_output_removes_the_output_folder(tmp_path):
    project = _make_project(tmp_path)
    document = DomainDocument(
        source_path=str(_write_file(tmp_path, "a.pdf", b"A")),
        markdown_path=str(_write_file(tmp_path, "a.md", b"# A")),
        json_path=str(_write_file(tmp_path, "a.json", b"{}")),
        title="A",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])
    reorganizer = Reorganizer()
    output_root = await reorganizer.reorganize(project, context)
    assert output_root.is_dir()

    await reorganizer.delete_output(project, context)

    assert not output_root.exists()


@pytest.mark.asyncio
async def test_delete_output_is_idempotent_when_nothing_to_delete(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    await Reorganizer().delete_output(project, context)  # no debe lanzar
