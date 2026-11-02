"""Tests de Reorganizer (copia física de documentos clasificados)."""

import os

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context import reorganizer as reorganizer_module
from doc_organize.context.reorganizer import Reorganizer, resolve_document_slug_parts
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.exceptions import IncompleteConversionArtifactsError, InvalidPathError
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
async def test_reorganize_copies_images_dir_alongside_markdown(tmp_path):
    """Regresión: las imágenes extraídas por `extract_images=True` deben quedar
    junto al `.md` reorganizado en el mismo layout relativo `img/<stem>/` que
    asume su referencia `![](img/<stem>/imagen.png)` (que no se reescribe) —
    antes se perdían por completo y el sitio servía imágenes rotas."""
    project = _make_project(tmp_path)
    source_dir = tmp_path / "originales"
    source_dir.mkdir()
    source = source_dir / "informe.pdf"
    source.write_bytes(b"%PDF-1.4 contenido")
    markdown = tmp_path / "informe.md"
    markdown.write_text("# Informe\n\n![](img/informe/foto.png)", encoding="utf-8")
    json_file = tmp_path / "informe.json"
    json_file.write_text('{"title": "Informe"}', encoding="utf-8")
    images_dir = tmp_path / "img" / "informe"
    images_dir.mkdir(parents=True)
    (images_dir / "foto.png").write_bytes(b"\x89PNG")

    document = DomainDocument(
        source_path=str(source),
        markdown_path=str(markdown),
        json_path=str(json_file),
        images_dir=str(images_dir),
        title="Informe",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])

    output_root = await Reorganizer().reorganize(project, context)

    target_dir = output_root / "calidad" / "pdf" / "informe"
    assert (target_dir / "img" / "informe" / "foto.png").read_bytes() == b"\x89PNG"


@pytest.mark.asyncio
async def test_reorganize_without_images_dir_does_not_fail(tmp_path):
    """La mayoría de documentos no tienen imágenes (`images_dir=None`) — no debe
    tratarse como artefacto incompleto ni fallar la copia."""
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

    output_root = await Reorganizer().reorganize(project, context)

    target_dir = output_root / "calidad" / "pdf" / "a"
    assert (target_dir / "a.pdf").is_file()
    assert not (target_dir / "img").exists()


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


def test_resolve_document_slug_parts_prefers_material_type_over_extension_when_set():
    """Modo manifiesto de taxonomía: `material_type` (tipo de material de origen) sustituye
    a la extensión como segmento de carpeta — el modo sin manifiesto (`material_type=None`,
    test anterior) queda con el comportamiento idéntico al de antes de esta sesión."""
    document = DomainDocument(
        source_path="/docs/x.pdf",
        markdown_path="/out/informe.md",
        json_path="/out/informe.json",
        title="X",
        document_type="pdf",
        material_type="normativa",
        confidence=0.9,
    )

    tipo, stem = resolve_document_slug_parts(document)

    assert tipo == "normativa"
    assert stem == "informe"


@pytest.mark.asyncio
async def test_reorganize_uses_material_type_as_folder_segment_when_set(tmp_path):
    project = _make_project(tmp_path)
    document = DomainDocument(
        source_path=str(_write_file(tmp_path, "politica.pdf", b"X")),
        markdown_path=str(_write_file(tmp_path, "politica.md", b"# X")),
        json_path=str(_write_file(tmp_path, "politica.json", b"{}")),
        title="Política",
        document_type="pdf",
        material_type="normativa",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="ciberseguridad", name="Ciberseguridad", documents=[document])])

    output_root = await Reorganizer().reorganize(project, context)

    assert (output_root / "ciberseguridad" / "normativa" / "politica" / "politica.pdf").is_file()
    assert not (output_root / "ciberseguridad" / "pdf").exists()


@pytest.mark.asyncio
async def test_reorganizer_destination_matches_site_generator_nav_path(tmp_path):
    """`Reorganizer` (destino real en disco) y `SiteGenerator` (ruta en el `nav`
    de `zensical.toml`) deben coincidir para el mismo documento — antes cada uno
    calculaba la misma fórmula por separado, sin nada que lo garantizara
    (AUDIT_CODE, sesión 2026-09-09)."""
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
    await SiteGenerator().generate(project, context, build=False)

    config = (tmp_path / "zensical.toml").read_text(encoding="utf-8")
    nav_relative_path = "calidad/pdf/informe/informe.md"
    assert nav_relative_path in config

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


# --- L-8a (G27): sin seguir enlaces simbólicos ---


def _link(link, target, *, is_dir: bool = False) -> None:
    """Enlace simbólico; en Windows sin privilegios, una unión (solo carpetas) o se salta el test."""
    try:
        link.symlink_to(target, target_is_directory=is_dir)
        return
    except OSError:
        if not (is_dir and os.name == "nt"):
            pytest.skip("El entorno no permite crear symlinks (privilegios insuficientes en Windows).")
    import _winapi  # solo existe en Windows

    _winapi.CreateJunction(str(target), str(link))


def _document(tmp_path, stem: str, *, source=None, images_dir=None) -> DomainDocument:
    return DomainDocument(
        source_path=str(source if source is not None else _write_file(tmp_path, f"{stem}.pdf", stem.encode())),
        markdown_path=str(_write_file(tmp_path, f"{stem}.md", f"# {stem}".encode())),
        json_path=str(_write_file(tmp_path, f"{stem}.json", b"{}")),
        title=stem,
        document_type="pdf",
        images_dir=str(images_dir) if images_dir is not None else None,
        confidence=0.9,
    )


def _project_dir(tmp_path) -> Project:
    (tmp_path / "proyecto").mkdir()
    return _make_project(tmp_path / "proyecto")


def _secret(tmp_path) -> Path:
    secret_dir = tmp_path / "fuera"
    secret_dir.mkdir()
    (secret_dir / "secreto.txt").write_bytes(b"SECRETO")
    return secret_dir


def _all_bytes_under(root) -> list[bytes]:
    return [path.read_bytes() for path in root.rglob("*") if path.is_file()]


@pytest.mark.asyncio
async def test_document_whose_original_is_a_link_fails_alone_without_copying(tmp_path):
    project = _project_dir(tmp_path)
    secret_dir = _secret(tmp_path)
    linked_source = tmp_path / "enlazado.pdf"
    _link(linked_source, secret_dir / "secreto.txt")
    linked = _document(tmp_path, "enlazado", source=linked_source)
    normal = _document(tmp_path, "normal")
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[linked, normal])])
    copied: list[tuple[int, int, str]] = []
    failed: list[tuple[int, int, str, str]] = []

    async def on_copied(index: int, total: int, path: str) -> None:
        copied.append((index, total, path))

    async def on_failed(index: int, total: int, path: str, error: str) -> None:
        failed.append((index, total, path, error))

    output_root = await Reorganizer().reorganize(project, context, on_copied, on_document_failed=on_failed)

    assert not (output_root / "calidad" / "pdf" / "enlazado").exists()
    assert (output_root / "calidad" / "pdf" / "normal" / "normal.pdf").read_bytes() == b"normal"
    assert b"SECRETO" not in _all_bytes_under(output_root)
    assert context.reorganize_failed_documents == [linked.source_path]
    assert [(index, total, path) for index, total, path, _error in failed] == [(1, 2, linked.source_path)]
    assert copied == [(2, 2, normal.source_path)]


@pytest.mark.asyncio
async def test_document_whose_images_dir_is_a_link_fails_alone(tmp_path):
    project = _project_dir(tmp_path)
    secret_dir = _secret(tmp_path)
    images_dir = tmp_path / "img" / "doc"
    images_dir.parent.mkdir()
    _link(images_dir, secret_dir, is_dir=True)
    document = _document(tmp_path, "doc", images_dir=images_dir)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])

    output_root = await Reorganizer().reorganize(project, context)

    assert not (output_root / "calidad" / "pdf" / "doc").exists()
    assert context.reorganize_failed_documents == [document.source_path]
    assert (secret_dir / "secreto.txt").read_bytes() == b"SECRETO"


@pytest.mark.asyncio
async def test_link_inside_images_dir_fails_without_partial_copy(tmp_path):
    project = _project_dir(tmp_path)
    secret_dir = _secret(tmp_path)
    images_dir = tmp_path / "img" / "doc"
    images_dir.mkdir(parents=True)
    (images_dir / "figura.png").write_bytes(b"PNG")
    _link(images_dir / "otra", secret_dir, is_dir=True)
    document = _document(tmp_path, "doc", images_dir=images_dir)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])

    output_root = await Reorganizer().reorganize(project, context)

    assert not (output_root / "calidad" / "pdf" / "doc").exists()
    assert context.reorganize_failed_documents == [document.source_path]


@pytest.mark.asyncio
async def test_output_folder_that_is_a_link_is_rejected_before_touching_anything(tmp_path):
    project = _project_dir(tmp_path)
    secret_dir = _secret(tmp_path)
    _link(tmp_path / "proyecto" / "organizado", secret_dir, is_dir=True)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[_document(tmp_path, "doc")])])

    with pytest.raises(InvalidPathError):
        await Reorganizer().reorganize(project, context)

    assert sorted(path.name for path in secret_dir.iterdir()) == ["secreto.txt"]


@pytest.mark.asyncio
async def test_links_in_place_of_domain_folders_are_removed_without_touching_their_target(tmp_path):
    project = _project_dir(tmp_path)
    output_root = tmp_path / "proyecto" / "organizado"
    output_root.mkdir()
    secret_dir = _secret(tmp_path)
    _link(output_root / "calidad", secret_dir, is_dir=True)  # dominio actual
    _link(output_root / "obsoleto", secret_dir, is_dir=True)  # dominio que ya no existe
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[_document(tmp_path, "doc")])])

    await Reorganizer().reorganize(project, context)

    assert (output_root / "calidad" / "pdf" / "doc" / "doc.pdf").is_file()
    assert not (output_root / "calidad").is_symlink()
    assert not os.path.lexists(output_root / "obsoleto")
    assert sorted(path.name for path in secret_dir.iterdir()) == ["secreto.txt"]


@pytest.mark.asyncio
async def test_delete_output_removes_only_the_link_when_output_folder_is_a_link(tmp_path):
    project = _project_dir(tmp_path)
    secret_dir = _secret(tmp_path)
    _link(tmp_path / "proyecto" / "organizado", secret_dir, is_dir=True)

    await Reorganizer().delete_output(project, _make_context(project, []))

    assert not os.path.lexists(tmp_path / "proyecto" / "organizado")
    assert (secret_dir / "secreto.txt").read_bytes() == b"SECRETO"


@pytest.mark.asyncio
async def test_failed_documents_are_recomputed_on_each_reorganization(tmp_path):
    project = _project_dir(tmp_path)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[_document(tmp_path, "doc")])])
    context.reorganize_failed_documents = ["/antiguo.pdf"]

    await Reorganizer().reorganize(project, context)

    assert context.reorganize_failed_documents == []


@pytest.mark.asyncio
async def test_copy_error_of_one_document_does_not_stop_the_rest(tmp_path, monkeypatch):
    """Cualquier `OSError` al copiar un documento (no solo un enlace) es un fallo de ese documento."""
    project = _project_dir(tmp_path)
    broken = _document(tmp_path, "roto")
    normal = _document(tmp_path, "normal")
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[broken, normal])])
    real_copy = reorganizer_module.copy_file_nofollow

    def flaky_copy(source, target, *, overwrite=False):
        if Path(source).name == "roto.md":
            raise PermissionError(13, "Permiso denegado", str(source))
        real_copy(source, target, overwrite=overwrite)

    monkeypatch.setattr(reorganizer_module, "copy_file_nofollow", flaky_copy)

    output_root = await Reorganizer().reorganize(project, context)

    assert not (output_root / "calidad" / "pdf" / "roto").exists()  # se borra la copia parcial (roto.pdf)
    assert (output_root / "calidad" / "pdf" / "normal" / "normal.md").is_file()
    assert context.reorganize_failed_documents == [broken.source_path]
