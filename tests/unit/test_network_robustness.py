"""Robustez en carpetas de red (G11 / L-9, 1.1.0) y duplicados desde la caché (G25).

Los cortes de red se simulan con `OSError(EIO)` en `hash_file`, `Path.stat` o la copia a duplicados; la conversión es
falsa (sin Docling).
"""

import errno
import json
import os
import sqlite3
import sys

from pathlib import Path
from typing import Any

import pytest

from doc_organize import ScanCommand, ScanOptions
from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import CacheEntry, ConversionResult, DocumentMetadata, DocumentStatus, DuplicateReason, ScanEventType
from doc_organize.dedup import DeduplicationManager
from doc_organize.projects import ProjectLayout
from doc_organize.scanner import DocumentScanner, document_scanner as scanner_module
from doc_organize.utils.hash_utils import hash_file
from doc_organize.utils.io_retry import is_transient_os_error, retry_io

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _eio(path: str = "") -> OSError:
    return OSError(errno.EIO, "Input/output error", path)


@pytest.fixture
def fake_conversion(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    converted: list[str] = []

    async def _convert(self: DocumentConverter, doc: DocumentMetadata, output_dir: Path, **_: Any) -> ConversionResult:
        converted.append(Path(doc.full_path).name)
        return ConversionResult(source_path=doc.full_path, success=True)

    monkeypatch.setattr(DocumentConverter, "convert_document", _convert)
    return converted


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path.resolve() / "origen"
    folder.mkdir()
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (folder / name).write_bytes(PDF + name.encode())
    return folder


class FlakyHash:
    """`hash_file` que falla `failures` veces con EIO para los ficheros indicados y anota cada llamada."""

    def __init__(self, failing: set[str], failures: int) -> None:
        self.failing = failing
        self.left = dict.fromkeys(failing, failures)
        self.calls: list[str] = []

    async def __call__(self, file_path: str, chunk_size: int = 65536) -> str:
        name = Path(file_path).name
        self.calls.append(name)
        if name in self.failing and self.left[name] > 0:
            self.left[name] -= 1
            raise OSError(f"Cannot read file {file_path}") from _eio(file_path)
        return await hash_file(file_path, chunk_size)


async def _scan(layout: ProjectLayout, source: Path, options: ScanOptions) -> Any:
    return [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(source)],
            output_dir=layout.conversion_dir,
            cache_db=layout.cache_db,
            folders_json=layout.folders_json,
            error_log_path=layout.scan_errors_log,
            options=options,
        )
    ]


# ----- utils.io_retry -----


def test_retry_io_retries_transient_errors_until_success() -> None:
    attempts: list[int] = []

    def _flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _eio()
        return "ok"

    assert retry_io(_flaky, retries=2, backoff_s=0, what="prueba") == "ok"
    assert len(attempts) == 3


def test_retry_io_gives_up_after_retries_and_skips_permanent_errors() -> None:
    attempts: list[int] = []

    def _always(exc: OSError) -> Any:
        def _call() -> None:
            attempts.append(1)
            raise exc

        return _call

    with pytest.raises(OSError, match="Input/output"):
        retry_io(_always(_eio()), retries=1, backoff_s=0, what="prueba")
    assert len(attempts) == 2

    attempts.clear()
    with pytest.raises(FileNotFoundError):
        retry_io(_always(FileNotFoundError("no existe")), retries=3, backoff_s=0, what="prueba")
    assert len(attempts) == 1


def test_wrapped_cause_decides_if_error_is_transient() -> None:
    wrapped_missing = OSError("Cannot read file")
    wrapped_missing.__cause__ = FileNotFoundError("no existe")
    wrapped_eio = OSError("Cannot read file")
    wrapped_eio.__cause__ = _eio()

    assert not is_transient_os_error(wrapped_missing)
    assert is_transient_os_error(wrapped_eio)
    assert not is_transient_os_error(ValueError("no es E/S"))


def test_io_retry_options_validate() -> None:
    assert (ScanOptions().io_retries, ScanOptions().document_timeout_s, ScanOptions().reuse_unchanged_hashes) == (0, None, False)
    with pytest.raises(ValueError, match="io_retries"):
        ScanOptions(io_retries=-1)
    with pytest.raises(ValueError, match="document_timeout_s"):
        ScanOptions(document_timeout_s=0)


# ----- DocumentScanner -----


@pytest.mark.asyncio
async def test_scanner_retries_hash_on_transient_error(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flaky = FlakyHash({"b.pdf"}, failures=2)
    monkeypatch.setattr(scanner_module, "hash_file", flaky)

    async with DocumentScanner(io_retries=2, io_retry_backoff_s=0) as scanner:
        result = await scanner.scan_folders([str(source)])

    assert sorted(Path(doc.full_path).name for doc in result.documents) == ["a.pdf", "b.pdf", "c.pdf"]
    assert result.unreadable_files == {}
    assert flaky.calls.count("b.pdf") == 3


@pytest.mark.asyncio
async def test_scanner_records_file_that_exhausts_retries_and_keeps_the_folder(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scanner_module, "hash_file", FlakyHash({"b.pdf"}, failures=5))

    async with DocumentScanner(io_retries=1, io_retry_backoff_s=0) as scanner:
        result = await scanner.scan_folders([str(source)])

    assert sorted(Path(doc.full_path).name for doc in result.documents) == ["a.pdf", "c.pdf"]
    assert list(result.unreadable_files) == [str(source / "b.pdf")]
    assert "hash" in result.unreadable_files[str(source / "b.pdf")]


@pytest.mark.asyncio
async def test_scanner_retries_metadata_read_on_transient_error(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_lstat = Path.lstat
    failures = {"left": 10**6}

    def _flaky_lstat(self: Path) -> os.stat_result:
        if self.name == "c.pdf" and failures["left"] > 0:
            failures["left"] -= 1
            raise _eio(str(self))
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", _flaky_lstat)

    async with DocumentScanner() as scanner:
        without_retries = await scanner.scan_folders([str(source)])
    failures["left"] = 1
    async with DocumentScanner(io_retries=1, io_retry_backoff_s=0) as scanner:
        with_retries = await scanner.scan_folders([str(source)])

    # El error de E/S no se confunde con «no es un fichero»: queda anotado (hasta 1.0.1 se omitía en silencio).
    assert list(without_retries.unreadable_files) == [str(source / "c.pdf")]
    assert len(with_retries.documents) == 3 and with_retries.unreadable_files == {}


@pytest.mark.asyncio
async def test_deleted_file_is_not_an_unreadable_file(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _gone(file_path: str, chunk_size: int = 65536) -> str:
        if file_path.endswith("a.pdf"):
            raise FileNotFoundError(file_path)
        return await hash_file(file_path, chunk_size)

    monkeypatch.setattr(scanner_module, "hash_file", _gone)

    async with DocumentScanner(io_retries=3, io_retry_backoff_s=0) as scanner:
        result = await scanner.scan_folders([str(source)])

    assert len(result.documents) == 2
    assert result.unreadable_files == {}


@pytest.mark.asyncio
async def test_scanner_reuses_hash_when_size_and_mtime_match(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with DocumentScanner() as scanner:
        first = await scanner.scan_folders([str(source)])
    known = {
        doc.full_path: CacheEntry(
            file_path=doc.full_path,
            sha256_hash=doc.sha256_hash,
            timestamp=doc.modified_time,
            status=DocumentStatus.NEW,
            size_bytes=doc.size_bytes,
        )
        for doc in first.documents
    }
    changed = source / "b.pdf"
    changed.write_bytes(PDF + b"contenido distinto y mas largo")
    counting = FlakyHash(set(), failures=0)
    monkeypatch.setattr(scanner_module, "hash_file", counting)

    async with DocumentScanner() as scanner:
        second = await scanner.scan_folders([str(source)], known_entries=known)

    assert counting.calls == ["b.pdf"]  # solo se rehashea lo que cambió de tamaño o fecha
    assert {doc.full_path: doc.sha256_hash for doc in second.documents if doc.full_path != str(changed)} == {
        path: entry.sha256_hash for path, entry in known.items() if path != str(changed)
    }


@pytest.mark.skipif(sys.platform == "win32", reason="crear symlinks en Windows exige privilegios")
@pytest.mark.asyncio
async def test_symlink_outside_root_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto.pdf").write_bytes(PDF)
    root = tmp_path / "raiz"
    root.mkdir()
    (root / "propio.pdf").write_bytes(PDF + b"propio")
    (root / "enlace").symlink_to(outside, target_is_directory=True)
    (root / "fichero.pdf").symlink_to(outside / "secreto.pdf")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(root)])

    assert [Path(doc.full_path).name for doc in result.documents] == ["propio.pdf"]


@pytest.mark.skipif(sys.platform != "win32", reason="las junctions solo existen en Windows")
@pytest.mark.asyncio
async def test_windows_junction_outside_root_is_not_followed(tmp_path: Path) -> None:
    import _winapi

    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto.pdf").write_bytes(PDF)
    root = tmp_path / "raiz"
    root.mkdir()
    (root / "propio.pdf").write_bytes(PDF + b"propio")
    _winapi.CreateJunction(str(outside), str(root / "union"))

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(root)])

    assert [Path(doc.full_path).name for doc in result.documents] == ["propio.pdf"]


# ----- ScanCommand -----


@pytest.mark.asyncio
async def test_scan_reports_unreadable_file_as_error_and_keeps_its_cache_with_force(
    tmp_path: Path, source: Path, fake_conversion: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, source, ScanOptions(use_ocr=False))
    monkeypatch.setattr(scanner_module, "hash_file", FlakyHash({"b.pdf"}, failures=10))

    events = await _scan(layout, source, ScanOptions(use_ocr=False, force=True, io_retries=1, io_retry_backoff_s=0))

    assert events[-1].event is ScanEventType.COMPLETED
    assert events[-1].data["io_errors"] == 1
    scanned = next(event for event in events if event.event is ScanEventType.SCANNED)
    assert any("b.pdf" in warning for warning in scanned.data["warnings"])
    errors = [json.loads(line) for line in layout.scan_errors_log.read_text(encoding="utf-8").splitlines()]
    assert [Path(entry["file_path"]).name for entry in errors[-1]["entries"]] == ["b.pdf"]
    async with CacheManager(layout.cache_db) as cache:
        assert str(source / "b.pdf") in await cache.load_cache()  # no se da por eliminado


@pytest.mark.asyncio
async def test_scan_reuse_unchanged_hashes_skips_rehash(
    tmp_path: Path, source: Path, fake_conversion: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, source, ScanOptions(use_ocr=False))
    counting = FlakyHash(set(), failures=0)
    monkeypatch.setattr(scanner_module, "hash_file", counting)

    events = await _scan(layout, source, ScanOptions(use_ocr=False, reuse_unchanged_hashes=True))
    assert counting.calls == []
    assert events[-1].data["unchanged"] == 3

    await _scan(layout, source, ScanOptions(use_ocr=False))  # por defecto se rehashea todo, como en 1.0
    assert sorted(counting.calls) == ["a.pdf", "b.pdf", "c.pdf"]


# ----- Deduplicación -----


@pytest.mark.asyncio
async def test_dedup_copy_retries_transient_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "origen"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(PDF)
    (folder / "b.pdf").write_bytes(PDF)
    original = DeduplicationManager._move_to_duplicates
    failures = {"left": 2}

    async def _flaky(self: DeduplicationManager, *args: Any, **kwargs: Any) -> None:
        if failures["left"] > 0:
            failures["left"] -= 1
            raise _eio()
        await original(self, *args, **kwargs)

    monkeypatch.setattr(DeduplicationManager, "_move_to_duplicates", _flaky)
    layout = ProjectLayout(tmp_path / "p")

    events = [
        event
        async for event in ScanCommand().deduplicate_streaming(
            [str(folder)], layout.duplicates_dir, layout.folders_json, mode="copy", io_retries=2, io_retry_backoff_s=0
        )
    ]

    assert events[-1].data["failed_paths"] == []
    assert events[-1].data["moved"] == 1
    assert (folder / "a.pdf").exists() and (folder / "b.pdf").exists()  # copiar no toca el origen


# ----- G25: caché con tamaño -----


@pytest.mark.asyncio
async def test_cache_stores_size_and_duplicates_come_from_cache(tmp_path: Path, fake_conversion: list[str]) -> None:
    folder = tmp_path.resolve() / "origen"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(PDF + b"igual")
    (folder / "copia de a.pdf").write_bytes(PDF + b"igual")
    (folder / "otro.pdf").write_bytes(PDF + b"otro")
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, folder, ScanOptions(use_ocr=False))

    async with CacheManager(layout.cache_db, read_only=True) as cache:
        entries = await cache.load_cache()
    docs = [DocumentMetadata.from_cache_entry(entry) for entry in entries.values()]

    assert {doc.display_name: doc.size_bytes for doc in docs} == {path.name: path.stat().st_size for path in folder.iterdir()}
    groups = DeduplicationManager().find_duplicates(docs)
    exact = [group for group in groups if group.reason == DuplicateReason.EXACT_DUPLICATE]
    assert len(exact) == 1
    assert sorted(doc.display_name for doc in [exact[0].canonical_doc, *exact[0].duplicates]) == ["a.pdf", "copia de a.pdf"]


def _old_cache(path: Path) -> None:
    """Caché de 1.0 (sin `size_bytes`)."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE cache_entries (file_path TEXT PRIMARY KEY, sha256_hash TEXT NOT NULL, timestamp REAL NOT NULL, "
            "status TEXT NOT NULL, conversion_status TEXT, error_message TEXT, error_retry_count INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute("INSERT INTO cache_entries VALUES ('/repo/a.pdf', ?, 1.0, 'new', 'success', NULL, 0)", ("ab" * 32,))
    conn.close()


@pytest.mark.asyncio
async def test_old_cache_is_read_without_size_and_migrated(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    _old_cache(db)

    async with CacheManager(db, read_only=True) as cache:
        (entry,) = (await cache.load_cache()).values()
        (page_entry,) = await cache.load_cache_page(limit=10, offset=0)
    assert entry.size_bytes is None and page_entry.size_bytes is None
    with pytest.raises(ValueError, match="1.1.0"):
        DocumentMetadata.from_cache_entry(entry)

    async with CacheManager(db) as cache:  # en escritura migra la columna
        await cache.save_entries([entry.model_copy(update={"size_bytes": 42})])
        assert (await cache.load_cache())["/repo/a.pdf"].size_bytes == 42


def test_old_cache_entry_json_still_loads() -> None:
    old = {"file_path": "/repo/a.pdf", "sha256_hash": "ab" * 32, "timestamp": 1.0, "status": "new", "conversion_status": "success"}

    entry = CacheEntry.model_validate_json(json.dumps(old))

    assert entry.size_bytes is None
