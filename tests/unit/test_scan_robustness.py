"""Robustez del escaneo (L-10a, L-10c, L-10d; huecos G16, G18 y G19 de doc_organize_web).

La conversión se sustituye por una falsa (sin Docling) que escribe el `.md`/`.json` donde lo haría `DocumentConverter`.
"""

import json

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from doc_organize import CancelToken, ProgressEvent, ScanCommand, ScanOptions, resolve_output_paths
from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, DocumentMetadata, ScanEvent, ScanEventType
from doc_organize.projects import ProjectLayout
from doc_organize.scanner import DocumentScanner

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

ConvertHook = Callable[[DocumentMetadata, int], ConversionResult | None]


class FakeConversion:
    """Conversión instantánea: escribe las salidas, anota las llamadas y deja intervenir a cada test con `hook`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.hook: ConvertHook | None = None

    async def convert(self, doc: DocumentMetadata, output_dir: Path, **kwargs: Any) -> ConversionResult:
        self.calls.append((doc.full_path, kwargs))
        if self.hook is not None:
            result = self.hook(doc, len(self.calls))
            if result is not None:
                return result
        markdown_path, json_path = resolve_output_paths(
            doc.full_path, output_dir, kwargs.get("scan_roots", ()), include_root_name=kwargs.get("include_root_name", False)
        )
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(doc.full_path, encoding="utf-8")
        json_path.write_text("{}", encoding="utf-8")
        return ConversionResult(source_path=doc.full_path, markdown_path=str(markdown_path), json_path=str(json_path), success=True)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeConversion:
    conversion = FakeConversion()

    async def _convert(self: DocumentConverter, doc: DocumentMetadata, output_dir: Path, **kwargs: Any) -> ConversionResult:
        return await conversion.convert(doc, output_dir, **kwargs)

    monkeypatch.setattr(DocumentConverter, "convert_document", _convert)
    return conversion


def _write_pdfs(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF + name.encode())


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path.resolve() / "origen"
    _write_pdfs(folder, "a.pdf", "b.pdf", "c.pdf", "d.pdf")
    return folder


async def _collect(layout: ProjectLayout, paths: list[Path], options: ScanOptions, **kwargs: Any) -> list[ScanEvent]:
    return [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(path) for path in paths],
            output_dir=layout.conversion_dir,
            cache_db=layout.cache_db,
            folders_json=layout.folders_json,
            error_log_path=layout.scan_errors_log,
            history_log_path=layout.scan_history_log,
            options=options,
            **kwargs,
        )
    ]


async def _cached_paths(cache_db: Path) -> set[str]:
    async with CacheManager(cache_db, read_only=True) as cache:
        return set(await cache.load_cache())


# --- L-10a: caché incremental -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exception_mid_scan_keeps_converted_in_cache_and_next_scan_does_not_reconvert(
    tmp_path: Path, source: Path, fake: FakeConversion
) -> None:
    layout = ProjectLayout(tmp_path / "p")
    options = ScanOptions(use_ocr=False, cache_save_every=0, cache_save_seconds=0)  # solo el guardado del camino de error

    def _fail_third(_doc: DocumentMetadata, call: int) -> ConversionResult | None:
        if call == 3:
            raise RuntimeError("worker caído")
        return None

    fake.hook = _fail_third
    with pytest.raises(RuntimeError, match="worker caído"):
        await _collect(layout, [source], options)

    converted_first = {path for path, _ in fake.calls[:2]}
    assert await _cached_paths(layout.cache_db) == converted_first

    fake.hook, fake.calls = None, []
    events = await _collect(layout, [source], options)

    assert events[-1].event is ScanEventType.COMPLETED
    assert {path for path, _ in fake.calls} == {str(source / n) for n in ("a.pdf", "b.pdf", "c.pdf", "d.pdf")} - converted_first


@pytest.mark.asyncio
async def test_cache_is_saved_every_n_documents_while_converting(tmp_path: Path, source: Path, fake: FakeConversion) -> None:
    """Lo que ve otro proceso a mitad de escaneo (p. ej. tras un `kill`): con `cache_save_every=2`, cada dos."""
    layout = ProjectLayout(tmp_path / "p")
    counts: list[int] = []

    async for event in ScanCommand().run_streaming(
        paths=[str(source)],
        output_dir=layout.conversion_dir,
        cache_db=layout.cache_db,
        folders_json=layout.folders_json,
        options=ScanOptions(use_ocr=False, cache_save_every=2, cache_save_seconds=0),
    ):
        if event.event is ScanEventType.FILE_STARTED:
            counts.append(len(await _cached_paths(layout.cache_db)))  # solo lectura, con el escaneo en curso

    assert counts == [0, 0, 2, 2]
    assert len(await _cached_paths(layout.cache_db)) == 4


@pytest.mark.asyncio
async def test_closing_the_stream_mid_scan_saves_converted(tmp_path: Path, source: Path, fake: FakeConversion) -> None:
    """Un consumidor que deja de leer (desconexión, timeout) cierra el generador: lo convertido se guarda igual."""
    layout = ProjectLayout(tmp_path / "p")
    stream = ScanCommand().run_streaming(
        paths=[str(source)],
        output_dir=layout.conversion_dir,
        cache_db=layout.cache_db,
        folders_json=layout.folders_json,
        options=ScanOptions(use_ocr=False, cache_save_every=0, cache_save_seconds=0),
    )
    converted = 0
    async for event in stream:
        if event.event is ScanEventType.FILE_CONVERTED:
            converted += 1
            if converted == 2:
                break
    await stream.aclose()  # type: ignore[attr-defined]

    assert len(await _cached_paths(layout.cache_db)) == 2


def test_scan_options_validate_save_intervals() -> None:
    with pytest.raises(ValueError):
        ScanOptions(cache_save_every=-1)
    with pytest.raises(ValueError):
        ScanOptions(cache_save_seconds=-0.5)


# --- L-10c: nombre de la raíz en la salida ------------------------------------------------------------------------------


@pytest.fixture
def two_roots(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path.resolve() / "datos"
    _write_pdfs(base / "2024", "x/a.pdf")
    _write_pdfs(base / "2025", "x/a.pdf")
    return base / "2024", base / "2025"


@pytest.mark.asyncio
async def test_two_roots_with_same_relative_path_warn_by_default(tmp_path: Path, two_roots: tuple[Path, Path], fake: FakeConversion) -> None:
    layout = ProjectLayout(tmp_path / "p")

    events = await _collect(layout, list(two_roots), ScanOptions(use_ocr=False))

    scanned = next(event for event in events if event.event is ScanEventType.SCANNED)
    assert any("misma salida" in warning and "root_name_in_output" in warning for warning in scanned.data["warnings"])
    assert all("include_root_name" not in kwargs for _, kwargs in fake.calls)  # llamada de siempre


@pytest.mark.asyncio
async def test_root_name_in_output_separates_roots(tmp_path: Path, two_roots: tuple[Path, Path], fake: FakeConversion) -> None:
    layout = ProjectLayout(tmp_path / "p")

    events = await _collect(layout, list(two_roots), ScanOptions(use_ocr=False, root_name_in_output=True))

    scanned = next(event for event in events if event.event is ScanEventType.SCANNED)
    assert not any("misma salida" in warning for warning in scanned.data["warnings"])
    assert (layout.conversion_dir / "2024" / "x" / "a.md").is_file()
    assert (layout.conversion_dir / "2025" / "x" / "a.md").is_file()


# --- L-10d: listado fallido y errores al cancelar -------------------------------------------------------------------------


@pytest.fixture
def unreadable(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], None]:
    """Hace que listar una carpeta concreta falle como un montaje de red caído."""
    blocked: set[Path] = set()
    original_iterdir = Path.iterdir

    def _iterdir(self: Path):  # type: ignore[no-untyped-def]
        if self in blocked:
            raise PermissionError(13, "Acceso denegado", str(self))
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _iterdir)
    return blocked.add


@pytest.mark.asyncio
async def test_scanner_reports_unreadable_dirs(tmp_path: Path, unreadable: Callable[[Path], None]) -> None:
    root = tmp_path.resolve() / "origen"
    _write_pdfs(root, "a.pdf", "red/b.pdf")
    unreadable(root / "red")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(root)])

    assert [Path(doc.full_path).name for doc in result.documents] == ["a.pdf"]
    assert result.unreadable_dirs == [str(root / "red")]


@pytest.mark.asyncio
async def test_force_with_unreadable_folder_keeps_its_outputs_and_cache(
    tmp_path: Path, fake: FakeConversion, unreadable: Callable[[Path], None]
) -> None:
    root = tmp_path.resolve() / "origen"
    _write_pdfs(root, "a.pdf", "red/b.pdf", "borrado.pdf")
    layout = ProjectLayout(tmp_path / "p")
    await _collect(layout, [root], ScanOptions(use_ocr=False))
    kept_md, kept_json = resolve_output_paths(str(root / "red" / "b.pdf"), layout.conversion_dir, [str(root)])
    gone_md, _ = resolve_output_paths(str(root / "borrado.pdf"), layout.conversion_dir, [str(root)])
    assert kept_md.is_file() and gone_md.is_file()

    (root / "borrado.pdf").unlink()
    unreadable(root / "red")
    events = await _collect(layout, [root], ScanOptions(use_ocr=False, force=True))

    assert kept_md.is_file() and kept_json.is_file()  # carpeta ilegible: no es un huérfano
    assert not gone_md.exists()  # un fichero borrado de verdad sí se limpia
    assert await _cached_paths(layout.cache_db) == {str(root / "a.pdf"), str(root / "red" / "b.pdf")}
    scanned = next(event for event in events if event.event is ScanEventType.SCANNED)
    assert any(str(root / "red") in warning for warning in scanned.data["warnings"])


@pytest.mark.asyncio
async def test_cancel_writes_error_report_of_processed_documents(tmp_path: Path, source: Path, fake: FakeConversion) -> None:
    layout = ProjectLayout(tmp_path / "p")
    token = CancelToken()

    def _first_fails(doc: DocumentMetadata, call: int) -> ConversionResult | None:
        if call == 1:
            return ConversionResult(source_path=doc.full_path, success=False, error="PDF dañado")
        return None

    def _cancel_after_two(event: ProgressEvent) -> None:
        if event.phase == "conversion" and event.processed == 2 and event.current is None:
            token.cancel()

    fake.hook = _first_fails
    events = await _collect(layout, [source], ScanOptions(use_ocr=False), on_progress=_cancel_after_two, cancel_token=token)

    assert events[-1].event is ScanEventType.CANCELLED
    lines = layout.scan_errors_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert [entry["file_path"] for entry in report["entries"]] == [fake.calls[0][0]]
    assert report["entries"][0]["error_message"] == "PDF dañado"


@pytest.mark.asyncio
async def test_same_stem_in_one_root_is_not_reported_as_root_collision(tmp_path: Path, fake: FakeConversion) -> None:
    """`a.pdf` y `a.docx` de una misma carpeta ya compartían salida antes; `root_name_in_output` no lo resuelve."""
    base = tmp_path.resolve() / "datos"
    _write_pdfs(base / "2024", "a.pdf", "a.png")
    _write_pdfs(base / "2025", "b.pdf")

    events = await _collect(ProjectLayout(tmp_path / "p"), [base / "2024", base / "2025"], ScanOptions(use_ocr=False))

    scanned = next(event for event in events if event.event is ScanEventType.SCANNED)
    assert not any("misma salida" in warning for warning in scanned.data["warnings"])


@pytest.mark.asyncio
async def test_failed_intermediate_save_does_not_stop_the_scan(
    tmp_path: Path, source: Path, fake: FakeConversion, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = ProjectLayout(tmp_path / "p")
    original_save = CacheManager.save_entries
    calls = 0

    async def _locked_once(self: CacheManager, entries: list[Any]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database is locked")
        await original_save(self, entries)

    monkeypatch.setattr(CacheManager, "save_entries", _locked_once)

    events = await _collect(layout, [source], ScanOptions(use_ocr=False, cache_save_every=1, cache_save_seconds=0))

    assert events[-1].event is ScanEventType.COMPLETED
    assert len(await _cached_paths(layout.cache_db)) == 4
