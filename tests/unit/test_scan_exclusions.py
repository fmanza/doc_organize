"""Exclusión de subcarpetas y patrones de nombre en el escaneo (G41 / L-19, 1.3.0).

La conversión se sustituye por una falsa (sin Docling), como en `test_scan_long_runs.py`; las salidas `.md`/`.json` se
crean a mano en la ruta que les deriva la librería para comprobar qué borra «forzar».
"""

import subprocess
import sys

from pathlib import Path
from typing import Any

import pytest

from pydantic import ValidationError

from doc_organize import ScanCommand, ScanOptions
from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, DocumentMetadata, ScanEventType
from doc_organize.projects import ProjectLayout
from doc_organize.projects.layout import resolve_output_paths
from doc_organize.scanner import DocumentScanner
from doc_organize.scanner.document_scanner import EntryFilter

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _tree(root: Path, *relative: str) -> Path:
    for rel in relative:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF + rel.encode())
    return root


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


def _names(documents: list[DocumentMetadata], root: Path) -> list[str]:
    return sorted(Path(doc.full_path).relative_to(root).as_posix() for doc in documents)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _tree(
        tmp_path.resolve() / "origen",
        "a.pdf",
        "borradores/b.pdf",
        "borradores/sub/c.pdf",
        "borradores2/d.pdf",
        "@eaDir/thumb.pdf",
        "docs/~$Informe.pdf",
        "docs/informe.pdf",
    )


# ===== DocumentScanner =====


@pytest.mark.asyncio
async def test_excluded_subtree_is_not_walked_nor_reported(source: Path) -> None:
    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(source)], exclude_paths=[str(source / "borradores")])

    assert _names(result.documents, source) == ["@eaDir/thumb.pdf", "a.pdf", "borradores2/d.pdf", "docs/informe.pdf", "docs/~$Informe.pdf"]
    assert result.unreadable_dirs == []
    assert result.unreadable_files == {}
    root_children = {child.name for child in result.tree.root_node.children[0].children or []}
    assert "borradores" not in root_children
    assert "borradores2" in root_children


@pytest.mark.asyncio
async def test_ignore_patterns_match_files_and_folders_by_name_case_insensitively(source: Path) -> None:
    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(source)], ignore_patterns=["@EADIR", "~$*"])

    assert _names(result.documents, source) == ["a.pdf", "borradores/b.pdf", "borradores/sub/c.pdf", "borradores2/d.pdf", "docs/informe.pdf"]


@pytest.mark.asyncio
async def test_patterns_never_apply_to_the_scanned_root(tmp_path: Path) -> None:
    root = _tree(tmp_path.resolve() / "borradores", "x.pdf")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(root)], ignore_patterns=["borradores"])

    assert _names(result.documents, root) == ["x.pdf"]


@pytest.mark.asyncio
async def test_excluded_path_case_follows_the_file_system(source: Path) -> None:
    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(source)], exclude_paths=[str(source / "BORRADORES")])

    names = _names(result.documents, source)
    if sys.platform == "win32":  # Windows no distingue mayúsculas: es la misma carpeta
        assert "borradores/b.pdf" not in names
    else:
        assert "borradores/b.pdf" in names


@pytest.mark.asyncio
async def test_missing_exclusion_is_not_an_error_and_excluded_root_is_empty(source: Path) -> None:
    async with DocumentScanner() as scanner:
        missing = await scanner.scan_folders([str(source)], exclude_paths=[str(source / "no-existe")])
        whole = await scanner.scan_folders([str(source)], exclude_paths=[str(source)])
        parent = await scanner.scan_folders([str(source / "borradores")], exclude_paths=[str(source)])

    assert len(missing.documents) == 7
    assert whole.documents == [] and whole.unreadable_dirs == []
    assert parent.documents == [] and parent.unreadable_dirs == []


@pytest.mark.asyncio
async def test_relative_exclusion_resolves_like_the_scanned_paths(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(source)

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders(["."], exclude_paths=["borradores"])

    assert "borradores/b.pdf" not in _names(result.documents, source)


@pytest.mark.skipif(sys.platform != "win32", reason="uniones de Windows")
@pytest.mark.asyncio
async def test_excluded_junction_is_dropped_without_following_it(source: Path, tmp_path: Path) -> None:
    outside = _tree(tmp_path.resolve() / "fuera", "externo.pdf")
    link = source / "enlace"
    _make_junction(link, outside)

    async with DocumentScanner() as scanner:
        kept = await scanner.scan_folders([str(source)])
        excluded = await scanner.scan_folders([str(source)], exclude_paths=[str(link)])

    def _children(result: Any) -> set[str]:
        return {child.name for child in result.tree.root_node.children[0].children or []}

    assert "enlace" in _children(kept)  # nodo opaco: nunca se sigue
    assert "enlace" not in _children(excluded)
    assert "fuera/externo.pdf" not in _names(excluded.documents, tmp_path.resolve())
    assert (outside / "externo.pdf").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="enlaces simbólicos sin privilegios")
@pytest.mark.asyncio
async def test_excluded_symlink_is_dropped_without_following_it(source: Path, tmp_path: Path) -> None:
    outside = _tree(tmp_path.resolve() / "fuera", "externo.pdf")
    link = source / "enlace"
    link.symlink_to(outside, target_is_directory=True)

    async with DocumentScanner() as scanner:
        excluded = await scanner.scan_folders([str(source)], exclude_paths=[str(link)])

    assert "enlace" not in {child.name for child in excluded.tree.root_node.children[0].children or []}
    assert (outside / "externo.pdf").exists()


def test_entry_filter_covers_cached_paths_without_touching_disk(tmp_path: Path) -> None:
    root = str(tmp_path.resolve() / "origen")
    entry_filter = EntryFilter.build([Path(root) / "borradores"], ["@eadir", "~$*"])

    assert entry_filter.covers_cached(str(Path(root) / "borradores" / "sub" / "c.pdf"), [root])
    assert not entry_filter.covers_cached(str(Path(root) / "borradores2" / "d.pdf"), [root])  # mismo prefijo, otra carpeta
    assert entry_filter.covers_cached(str(Path(root) / "@eaDir" / "thumb.pdf"), [root])
    assert entry_filter.covers_cached(str(Path(root) / "docs" / "~$Informe.pdf"), [root])
    assert not entry_filter.covers_cached(str(Path(root) / "docs" / "informe.pdf"), [root])
    # Un tramo por encima de la raíz no cuenta: los patrones no se aplican a la raíz ni a lo que hay sobre ella.
    assert not EntryFilter.build((), ["origen"]).covers_cached(str(Path(root) / "a.pdf"), [root])


# ===== ScanOptions =====


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ignore_patterns", [""], "vacíos"),
        ("ignore_patterns", ["  "], "vacíos"),
        ("ignore_patterns", ["a/b"], "separadores"),
        ("ignore_patterns", ["a\\b"], "separadores"),
        ("ignore_patterns", ["x" * 65], "64"),
        ("exclude_paths", [""], "vacías"),
    ],
)
def test_scan_options_validates_exclusions(field: str, value: list[str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ScanOptions(**{field: value})


def test_scan_options_defaults_have_no_exclusions() -> None:
    options = ScanOptions()

    assert options.exclude_paths == [] and options.ignore_patterns == []
    assert ScanOptions(ignore_patterns=["x" * 64]).ignore_patterns == ["x" * 64]


# ===== ScanCommand =====


class FakeConversion:
    def __init__(self) -> None:
        self.converted: list[str] = []

    async def convert(self, doc: DocumentMetadata, output_dir: Path, **kwargs: Any) -> ConversionResult:
        self.converted.append(Path(doc.full_path).name)
        return ConversionResult(source_path=doc.full_path, success=True)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeConversion:
    conversion = FakeConversion()

    async def _convert(self: DocumentConverter, doc: DocumentMetadata, output_dir: Path, **kwargs: Any) -> ConversionResult:
        return await conversion.convert(doc, output_dir, **kwargs)

    monkeypatch.setattr(DocumentConverter, "convert_document", _convert)
    return conversion


async def _scan(layout: ProjectLayout, source: Path, options: ScanOptions) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    async for event in ScanCommand().run_streaming(
        paths=[str(source)],
        output_dir=layout.conversion_dir,
        cache_db=layout.cache_db,
        folders_json=layout.folders_json,
        options=options,
    ):
        if event.event is ScanEventType.COMPLETED:
            summary = dict(event.data)
    return summary


async def _cached(layout: ProjectLayout, source: Path) -> list[str]:
    async with CacheManager(layout.cache_db) as cache:
        return sorted(Path(path).relative_to(source).as_posix() for path in await cache.load_cache())


def _write_outputs(layout: ProjectLayout, source: Path, *relative: str) -> dict[str, Path]:
    outputs = {}
    for rel in relative:
        markdown, json_file = resolve_output_paths(str(source / rel), layout.conversion_dir, [str(source)])
        for path in (markdown, json_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        outputs[rel] = markdown
    return outputs


@pytest.mark.asyncio
async def test_without_force_excluded_entries_are_kept_and_return_unchanged(tmp_path: Path, source: Path, fake: FakeConversion) -> None:
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, source, ScanOptions(use_ocr=False))
    outputs = _write_outputs(layout, source, "borradores/b.pdf", "@eaDir/thumb.pdf")
    fake.converted.clear()

    excluded = ScanOptions(use_ocr=False, exclude_paths=[str(source / "borradores")], ignore_patterns=["@eaDir"])
    summary = await _scan(layout, source, excluded)

    assert summary["excluded_cached"] == 3
    assert summary["scanned"] == 4
    assert summary["io_errors"] == 0
    assert fake.converted == []
    assert len(await _cached(layout, source)) == 7  # la caché no pierde nada
    assert all(path.exists() for path in outputs.values())

    restored = await _scan(layout, source, ScanOptions(use_ocr=False))  # quitar la exclusión no reconvierte

    assert restored["unchanged"] == 7 and restored["new"] == 0
    assert restored["excluded_cached"] == 0
    assert fake.converted == []


@pytest.mark.asyncio
async def test_with_force_excluded_entries_are_orphans_but_unreadable_are_kept(
    tmp_path: Path, source: Path, fake: FakeConversion, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, source, ScanOptions(use_ocr=False))
    outputs = _write_outputs(layout, source, "borradores/b.pdf", "@eaDir/thumb.pdf", "docs/informe.pdf")
    unreadable = source / "docs"
    original_iterdir = Path.iterdir

    def _iterdir(self: Path) -> Any:
        if self == unreadable:
            raise PermissionError(13, "sin permiso", str(self))
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _iterdir)
    fake.converted.clear()

    summary = await _scan(
        layout, source, ScanOptions(use_ocr=False, force=True, exclude_paths=[str(source / "borradores")], ignore_patterns=["@eaDir"])
    )

    assert summary["excluded_cached"] == 3
    assert await _cached(layout, source) == ["a.pdf", "borradores2/d.pdf", "docs/informe.pdf", "docs/~$Informe.pdf"]
    assert not outputs["borradores/b.pdf"].exists()
    assert not outputs["@eaDir/thumb.pdf"].exists()
    assert outputs["docs/informe.pdf"].exists()  # carpeta ilegible: protegida (L-10d)
    assert sorted(fake.converted) == ["a.pdf", "d.pdf"]

    monkeypatch.setattr(Path, "iterdir", original_iterdir)
    fake.converted.clear()
    restored = await _scan(layout, source, ScanOptions(use_ocr=False))  # lo borrado por «forzar» vuelve como nuevo

    assert restored["new"] == 3
    assert sorted(fake.converted) == ["b.pdf", "c.pdf", "thumb.pdf"]


@pytest.mark.asyncio
async def test_defaults_do_not_pass_new_arguments_to_scan_folders(tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    original = DocumentScanner.scan_folders

    async def _spy(self: DocumentScanner, *args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(DocumentScanner, "scan_folders", _spy)
    layout = ProjectLayout(tmp_path / "p")
    summary = await _scan(layout, source, ScanOptions(use_ocr=False, force=False))

    assert "exclude_paths" not in calls[0] and "ignore_patterns" not in calls[0]
    assert summary["excluded_cached"] == 0
