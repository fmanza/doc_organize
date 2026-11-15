"""Metadatos de fichero (1.5.0): tipo MIME, fecha de creación, permisos y propietario, en el escaneo y en la caché."""

import getpass
import os
import sqlite3
import sys

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from doc_organize import ScanCommand, ScanOptions
from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import CacheEntry, ConversionResult, DocumentMetadata, DocumentStatus, ScanEventType
from doc_organize.projects import ProjectLayout
from doc_organize.scanner import DocumentScanner
from doc_organize.utils.metadata_detector import creation_time, file_owner, file_permissions, guess_mime_type

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
HAS_BIRTHTIME = sys.platform in ("win32", "darwin")


def test_mime_type_comes_from_the_extension() -> None:
    assert guess_mime_type("Informe.PDF") == "application/pdf"
    assert guess_mime_type("notas.txt") == "text/plain"
    assert guess_mime_type("datos.extension-que-no-existe") is None


def test_creation_time_is_none_without_birthtime() -> None:
    assert creation_time(SimpleNamespace(st_ctime=1.0, st_mtime=2.0)) is None  # type: ignore[arg-type]
    assert creation_time(SimpleNamespace(st_birthtime=5.0, st_ctime=1.0)) == 5.0  # type: ignore[arg-type]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX")
def test_permissions_are_posix_octal(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(PDF)
    path.chmod(0o640)
    assert file_permissions(path.stat()) == "640"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows")
def test_permissions_are_none_on_windows(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(PDF)
    assert file_permissions(path.stat()) is None


def test_owner_is_the_current_account(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(PDF)
    owner = file_owner(path, path.stat())
    assert owner is not None
    # En Windows: DOMINIO\usuario (o el grupo Administradores si la cuenta es administradora y la política lo asigna).
    if sys.platform == "win32":
        assert "\\" in owner
    else:
        assert owner == getpass.getuser()


@pytest.mark.asyncio
async def test_scanner_fills_file_metadata_and_owner_only_on_request(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(PDF)

    async with DocumentScanner() as scanner:
        (doc,) = (await scanner.scan_folders([str(tmp_path)])).documents
    assert doc.mime_type == "application/pdf"
    assert (doc.created_time is not None) is HAS_BIRTHTIME
    assert (doc.file_permissions is None) is (sys.platform == "win32")
    assert doc.owner_name is None

    async with DocumentScanner(capture_owner=True) as scanner:
        (doc,) = (await scanner.scan_folders([str(tmp_path)])).documents
    assert doc.owner_name == file_owner(tmp_path / "a.pdf", (tmp_path / "a.pdf").stat())


def test_from_cache_entry_keeps_file_metadata() -> None:
    entry = CacheEntry(
        file_path="/repo/a.pdf",
        sha256_hash="ab" * 32,
        timestamp=2.0,
        status=DocumentStatus.UNCHANGED,
        size_bytes=10,
        created_time=1.0,
        mime_type="application/pdf",
        file_permissions="644",
        owner_name="ana",
    )
    doc = DocumentMetadata.from_cache_entry(entry)
    assert (doc.created_time, doc.mime_type, doc.file_permissions, doc.owner_name) == (1.0, "application/pdf", "644", "ana")


def _cache_1_4(path: Path) -> None:
    """Caché de 1.1.0-1.4.0: con `size_bytes`, sin los metadatos de fichero."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE cache_entries (file_path TEXT PRIMARY KEY, sha256_hash TEXT NOT NULL, timestamp REAL NOT NULL, "
            "status TEXT NOT NULL, conversion_status TEXT, error_message TEXT, error_retry_count INTEGER NOT NULL DEFAULT 0, "
            "size_bytes INTEGER)"
        )
        conn.execute("INSERT INTO cache_entries VALUES ('/repo/a.pdf', ?, 1.0, 'new', 'success', NULL, 0, 7)", ("ab" * 32,))
    conn.close()


@pytest.mark.asyncio
async def test_1_4_cache_is_read_and_migrated(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    _cache_1_4(db)

    async with CacheManager(db, read_only=True) as cache:
        (entry,) = (await cache.load_cache()).values()
        (page_entry,) = await cache.load_cache_page(limit=10, offset=0, order_by="size_bytes")
    assert entry.size_bytes == 7
    assert page_entry.size_bytes == 7
    assert (entry.created_time, entry.mime_type, entry.file_permissions, entry.owner_name) == (None, None, None, None)

    update = {"created_time": 1.5, "mime_type": "application/pdf", "file_permissions": "600", "owner_name": "ana"}
    async with CacheManager(db) as cache:  # en escritura migra las columnas
        await cache.save_entries([entry.model_copy(update=update)])
    async with CacheManager(db, read_only=True) as cache:
        saved = (await cache.load_cache())["/repo/a.pdf"]
    assert saved.model_dump(include=set(update)) == update
    assert saved.size_bytes == 7


# ----- ScanCommand -----


@pytest.fixture
def fake_conversion(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    converted: list[str] = []

    async def _convert(self: DocumentConverter, doc: DocumentMetadata, output_dir: Path, **_: Any) -> ConversionResult:
        converted.append(Path(doc.full_path).name)
        return ConversionResult(source_path=doc.full_path, success=True)

    monkeypatch.setattr(DocumentConverter, "convert_document", _convert)
    return converted


async def _scan(layout: ProjectLayout, source: Path, options: ScanOptions) -> None:
    async for _ in ScanCommand().run_streaming(
        paths=[str(source)],
        output_dir=layout.conversion_dir,
        cache_db=layout.cache_db,
        folders_json=layout.folders_json,
        error_log_path=layout.scan_errors_log,
        options=options,
    ):
        pass


async def _cached(layout: ProjectLayout) -> CacheEntry:
    async with CacheManager(layout.cache_db, read_only=True) as cache:
        (entry,) = (await cache.load_cache()).values()
    return entry


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_conversion")
async def test_scan_stores_file_metadata_in_the_cache(tmp_path: Path) -> None:
    source = tmp_path.resolve() / "origen"
    source.mkdir()
    (source / "a.pdf").write_bytes(PDF)
    layout = ProjectLayout(tmp_path / "p")

    await _scan(layout, source, ScanOptions(use_ocr=False))
    entry = await _cached(layout)
    assert entry.mime_type == "application/pdf"
    assert (entry.created_time is not None) is HAS_BIRTHTIME
    assert entry.owner_name is None


@pytest.mark.asyncio
async def test_unchanged_documents_get_their_file_metadata_refreshed(tmp_path: Path, fake_conversion: list[str]) -> None:
    source = tmp_path.resolve() / "origen"
    source.mkdir()
    (source / "a.pdf").write_bytes(PDF)
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, source, ScanOptions(use_ocr=False))
    async with CacheManager(layout.cache_db) as cache:  # como si la hubiera escrito 1.4.0
        old = await _cached(layout)
        await cache.save_entries([old.model_copy(update={"mime_type": None, "created_time": None})])

    await _scan(layout, source, ScanOptions(use_ocr=False, capture_owner=True))

    assert fake_conversion == ["a.pdf"]  # el segundo escaneo no reconvierte
    entry = await _cached(layout)
    assert entry.status == DocumentStatus.NEW  # el estado de la entrada no se toca
    assert entry.mime_type == "application/pdf"
    assert entry.owner_name == file_owner(source / "a.pdf", os.stat(source / "a.pdf"))


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_conversion")
async def test_failed_metadata_refresh_does_not_stop_the_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path.resolve() / "origen"
    source.mkdir()
    (source / "a.pdf").write_bytes(PDF)
    layout = ProjectLayout(tmp_path / "p")
    await _scan(layout, source, ScanOptions(use_ocr=False))

    async def _locked(self: CacheManager, entries: list[CacheEntry]) -> None:
        if entries:  # el guardado final del escaneo, sin conversiones, va vacío y no toca la base
            raise RuntimeError("database is locked")

    monkeypatch.setattr(CacheManager, "save_entries", _locked)
    events = [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(source)],
            output_dir=layout.conversion_dir,
            cache_db=layout.cache_db,
            folders_json=layout.folders_json,
            error_log_path=layout.scan_errors_log,
            options=ScanOptions(use_ocr=False, capture_owner=True),  # el propietario cambia: hay que refrescar
        )
    ]
    assert events[-1].event is ScanEventType.COMPLETED
