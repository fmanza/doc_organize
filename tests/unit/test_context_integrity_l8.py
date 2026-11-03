"""Tests de integridad y seguridad del contexto (L-8d…L-8f, 0.14.0; huecos G30–G32 de doc_organize_web)."""

import json
import os
import sys

from datetime import UTC, datetime
from pathlib import Path

import pydantic
import pytest

from doc_organize import resolve_organized_paths
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.context.taxonomy_manifest import save_taxonomy_manifest
from doc_organize.core.exceptions import ContextError, InvalidPathError
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.utils import atomic_write
from doc_organize.utils.atomic_write import write_text_atomic


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, relative_dir: str, stem: str, *, with_images: bool = False) -> DomainDocument:
    """Original en `origen/<relative_dir>/`, `.md`/`.json` en `Conversión/<relative_dir>/` (como el escaneo)."""
    source_dir = tmp_path / "origen" / relative_dir
    conversion_dir = tmp_path / "Conversión" / relative_dir
    source_dir.mkdir(parents=True, exist_ok=True)
    conversion_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / f"{stem}.pdf"
    source.write_bytes(f"pdf {relative_dir}/{stem}".encode())
    markdown = conversion_dir / f"{stem}.md"
    markdown.write_text(f"# {relative_dir}/{stem}\n![](img/{stem}/a.png)\n", encoding="utf-8")
    json_file = conversion_dir / f"{stem}.json"
    json_file.write_text('{"title": "t", "chunks": []}', encoding="utf-8")
    images_dir = None
    if with_images:
        images = conversion_dir / "img" / stem
        images.mkdir(parents=True)
        (images / "a.png").write_bytes(b"png " + relative_dir.encode())
        images_dir = str(images)
    return DomainDocument(
        source_path=str(source),
        markdown_path=str(markdown),
        json_path=str(json_file),
        images_dir=images_dir,
        title=f"{relative_dir}/{stem}",
        document_type="pdf",
        confidence=1.0,
    )


def _context(domains: list[Domain], **kwargs) -> Context:
    now = datetime.now(UTC).isoformat()
    return Context(project_name="Demo", domains=domains, created_at=now, updated_at=now, **kwargs)


def _link(link: Path, target: Path, *, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except OSError:
        pytest.skip("El entorno no permite crear symlinks (privilegios insuficientes en Windows).")


# --- L-8d: colisiones de nombre al reorganizar -------------------------------------------------------------------


def test_without_collisions_paths_are_identical_to_0_13(tmp_path):
    documents = [_document(tmp_path, "a", "acta"), _document(tmp_path, "b", "informe")]
    domain = Domain(slug="calidad", name="Calidad", documents=documents)

    assert resolve_organized_paths(domain, tmp_path) == ["calidad/pdf/acta/acta.md", "calidad/pdf/informe/informe.md"]


def test_case_insensitive_collision_suffixes_every_member(tmp_path):
    documents = [_document(tmp_path, "a", "Acta"), _document(tmp_path, "b", "acta"), _document(tmp_path, "c", "informe")]
    domain = Domain(slug="calidad", name="Calidad", documents=documents)

    paths = resolve_organized_paths(domain, tmp_path)

    folders = [path.split("/")[2] for path in paths]
    assert folders[0].startswith("Acta-") and len(folders[0]) == len("Acta-") + 8
    assert folders[1].startswith("acta-") and len(folders[1]) == len("acta-") + 8
    assert folders[0].casefold() != folders[1].casefold()
    assert folders[2] == "informe"  # sin colisión, sin sufijo
    assert paths[0].endswith("/Acta.md") and paths[1].endswith("/acta.md")


def test_collision_suffix_is_deterministic_and_order_independent(tmp_path):
    first = _document(tmp_path, "a", "acta")
    second = _document(tmp_path, "b", "acta")

    forward = resolve_organized_paths(Domain(slug="d", name="D", documents=[first, second]), tmp_path)
    backward = resolve_organized_paths(Domain(slug="d", name="D", documents=[second, first]), tmp_path)

    assert forward == list(reversed(backward))
    assert forward == resolve_organized_paths(Domain(slug="d", name="D", documents=[first, second]), tmp_path)


def test_same_stem_in_different_types_does_not_collide(tmp_path):
    pdf = _document(tmp_path, "a", "acta")
    docx = _document(tmp_path, "b", "acta").model_copy(update={"document_type": "docx"})

    paths = resolve_organized_paths(Domain(slug="d", name="D", documents=[pdf, docx]), tmp_path)

    assert paths == ["d/pdf/acta/acta.md", "d/docx/acta/acta.md"]


@pytest.mark.asyncio
async def test_reorganize_keeps_a_copy_of_each_colliding_document(tmp_path):
    project = _project(tmp_path)
    documents = [_document(tmp_path, "a", "Acta", with_images=True), _document(tmp_path, "b", "acta", with_images=True)]
    context = _context([Domain(slug="calidad", name="Calidad", documents=documents)])

    output_root = await Reorganizer().reorganize(project, context)

    expected = resolve_organized_paths(context.domains[0], tmp_path)
    for document, organized_path in zip(context.domains[0].documents, expected, strict=True):
        assert document.organized_path == organized_path
        copied_md = output_root / organized_path
        assert copied_md.read_text(encoding="utf-8") == Path(document.markdown_path).read_text(encoding="utf-8")
        stem = Path(document.markdown_path).stem
        assert (copied_md.parent / f"{stem}.pdf").read_bytes() == Path(document.source_path).read_bytes()
        assert (copied_md.parent / "img" / stem / "a.png").is_file()  # el .md sigue resolviendo sus imágenes
    assert context.reorganize_failed_documents == []


@pytest.mark.asyncio
async def test_site_nav_matches_reorganized_paths_with_collisions(tmp_path):
    project = _project(tmp_path)
    documents = [_document(tmp_path, "a", "acta"), _document(tmp_path, "b", "acta")]
    context = _context([Domain(slug="calidad", name="Calidad", documents=documents)])
    output_root = await Reorganizer().reorganize(project, context)

    result = await SiteGenerator().generate(project, context, build=False)

    config = result.config_path.read_text(encoding="utf-8")
    for document in context.domains[0].documents:
        assert document.organized_path is not None
        assert f'"{document.organized_path}"' in config
        assert (output_root / document.organized_path).is_file()


@pytest.mark.asyncio
async def test_manipulated_organized_path_in_index_is_ignored(tmp_path):
    project = _project(tmp_path)
    document = _document(tmp_path, "a", "acta").model_copy(update={"organized_path": "../../fuera/acta.md"})
    context = _context([Domain(slug="calidad", name="Calidad", documents=[document])])

    output_root = await Reorganizer().reorganize(project, context)

    assert context.domains[0].documents[0].organized_path == "calidad/pdf/acta/acta.md"
    assert (output_root / "calidad/pdf/acta/acta.md").is_file()
    assert not (tmp_path.parent / "fuera").exists()


@pytest.mark.asyncio
async def test_context_builder_persists_organized_path(tmp_path):
    from doc_organize.context.context_builder import ContextBuilder
    from doc_organize.core.models import ConversionResult

    project = _project(tmp_path)
    converted = []
    for relative_dir in ("a/Calidad", "b/Calidad"):  # la Sub-fase A mira la carpeta contenedora
        document = _document(tmp_path, relative_dir, "acta")
        converted.append(
            ConversionResult(source_path=document.source_path, markdown_path=document.markdown_path, json_path=document.json_path, success=True)
        )

    context = await ContextBuilder().build(project, converted, candidate_domains=["calidad"], threshold=0.0)

    reloaded = await ContextRegistry().load_context(project)
    paths = [document.organized_path for domain in reloaded.domains for document in domain.documents]
    assert len(paths) == 2 and None not in paths and len(set(paths)) == 2
    assert paths == [document.organized_path for domain in context.domains for document in domain.documents]


# --- L-8e: temporales que no siguen enlaces ----------------------------------------------------------------------


def test_write_text_atomic_writes_and_leaves_no_temporaries(tmp_path):
    target = tmp_path / "context.json"

    write_text_atomic(target, '{"a": 1}')
    write_text_atomic(target, '{"a": 2}')

    assert target.read_text(encoding="utf-8") == '{"a": 2}'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["context.json"]


@pytest.mark.parametrize("planted_name", ["context.tmp", "context.json.tmp"])
def test_planted_link_at_old_fixed_temporary_name_is_never_written_through(tmp_path, planted_name):
    secret = tmp_path / "secreto.txt"
    secret.write_text("no tocar", encoding="utf-8")
    _link(tmp_path / planted_name, secret)

    write_text_atomic(tmp_path / "context.json", "nuevo")

    assert secret.read_text(encoding="utf-8") == "no tocar"
    assert (tmp_path / "context.json").read_text(encoding="utf-8") == "nuevo"


def test_link_at_destination_is_replaced_not_followed(tmp_path):
    secret = tmp_path / "secreto.txt"
    secret.write_text("no tocar", encoding="utf-8")
    destination = tmp_path / "index.md"
    _link(destination, secret)

    write_text_atomic(destination, "nuevo")

    assert secret.read_text(encoding="utf-8") == "no tocar"
    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "nuevo"


def test_temporary_is_created_exclusively_with_unpredictable_name(tmp_path, monkeypatch):
    created: list[str] = []
    real_mkstemp = atomic_write.tempfile.mkstemp

    def spy(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        created.append(name)
        return fd, name

    monkeypatch.setattr(atomic_write.tempfile, "mkstemp", spy)
    write_text_atomic(tmp_path / "zensical.toml", "a")
    write_text_atomic(tmp_path / "zensical.toml", "b")

    assert len(set(created)) == 2
    assert all(Path(name).parent == tmp_path for name in created)  # misma carpeta: os.replace atómico


def test_failed_replace_keeps_target_and_removes_temporary(tmp_path, monkeypatch):
    target = tmp_path / "DOMAIN.md"
    target.write_text("anterior", encoding="utf-8")

    def broken_replace(_src, _dst):
        raise OSError("disco lleno")

    monkeypatch.setattr(atomic_write.os, "replace", broken_replace)
    with pytest.raises(OSError, match="disco lleno"):
        write_text_atomic(target, "nuevo")

    assert target.read_text(encoding="utf-8") == "anterior"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["DOMAIN.md"]


@pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")
def test_existing_permissions_are_preserved(tmp_path):
    target = tmp_path / "context.json"
    target.write_text("x", encoding="utf-8")
    os.chmod(target, 0o640)

    write_text_atomic(target, "y")

    assert target.stat().st_mode & 0o777 == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")
def test_new_file_is_not_private_like_mkstemp(tmp_path):
    target = tmp_path / "index.md"

    write_text_atomic(target, "y")

    assert target.stat().st_mode & 0o777 == 0o666 & ~atomic_write._UMASK


@pytest.mark.asyncio
async def test_all_context_writers_ignore_planted_fixed_temporaries(tmp_path):
    """context.json, DOMAIN.md, index.json, index.md, zensical.toml y taxonomy_manifest.md (L-8e)."""
    project = _project(tmp_path)
    secret = tmp_path / "secreto.txt"
    secret.write_text("no tocar", encoding="utf-8")
    domain_dir = tmp_path / "domains" / "calidad"
    domain_dir.mkdir(parents=True)
    output_dir = tmp_path / "organizado"
    output_dir.mkdir()
    for planted in (
        tmp_path / "context.tmp",
        domain_dir / "DOMAIN.tmp",
        domain_dir / "index.tmp",
        output_dir / "index.md.tmp",
        tmp_path / "zensical.toml.tmp",
        tmp_path / "taxonomy_manifest.tmp",
    ):
        _link(planted, secret)

    context = _context([Domain(slug="calidad", name="Calidad", documents=[_document(tmp_path, "a", "acta")])])
    await ContextRegistry().save_context(project, context)
    await Reorganizer().reorganize(project, context)
    await SiteGenerator().generate(project, context, build=False)
    await save_taxonomy_manifest(
        project, "---\ndomains:\n  - slug: calidad\n    name: Calidad\nmaterial_types:\n  - slug: acta\n    name: Acta\n---\n"
    )

    assert secret.read_text(encoding="utf-8") == "no tocar"
    for written in (tmp_path / "context.json", domain_dir / "DOMAIN.md", domain_dir / "index.json", output_dir / "index.md"):
        assert written.is_file() and not written.is_symlink()
    assert (tmp_path / "zensical.toml").is_file()
    assert (tmp_path / "taxonomy_manifest.md").is_file()


# --- L-8f: output_folder_name validado al leer context.json --------------------------------------------------------


_INVALID_NAMES = ["..", "../fuera", "/etc", "C:\\Windows", "Conversión", "conversión", "domains", "site", "  ", "a/b"]


@pytest.mark.parametrize("name", _INVALID_NAMES)
def test_context_rejects_invalid_output_folder_name(name):
    with pytest.raises(pydantic.ValidationError):
        _context([], output_folder_name=name)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["..", "/tmp/x", "Conversión"])
async def test_load_context_rejects_manipulated_output_folder_name(tmp_path, name):
    project = _project(tmp_path)
    registry = ContextRegistry()
    await registry.save_context(project, _context([]))
    context_file = tmp_path / "context.json"
    payload = json.loads(context_file.read_text(encoding="utf-8"))
    payload["output_folder_name"] = name
    context_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContextError, match="output_folder_name"):
        await registry.load_context(project)


@pytest.mark.asyncio
async def test_load_context_keeps_valid_output_folder_name(tmp_path):
    project = _project(tmp_path)
    registry = ContextRegistry()
    await registry.save_context(project, _context([], output_folder_name="docs publicados"))

    assert (await registry.load_context(project)).output_folder_name == "docs publicados"


@pytest.mark.asyncio
async def test_reorganizer_revalidates_output_folder_name_assigned_after_construction(tmp_path):
    project = _project(tmp_path)
    context = _context([])
    context.output_folder_name = "../fuera"  # sin `validate_assignment`: la defensa está en Reorganizer

    with pytest.raises(InvalidPathError):
        await Reorganizer().reorganize(project, context)
    with pytest.raises(InvalidPathError):
        await Reorganizer().delete_output(project, context)
    assert not (tmp_path.parent / "fuera").exists()
