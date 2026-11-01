"""ZIP de exportación en streaming y vista previa (L-7, G8): contenido, vista previa == ZIP, varias cachés, cancelación."""

import io
import json
import os
import zipfile

from pathlib import Path

import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.exceptions import InvalidPathError, OperationCancelledError
from doc_organize.core.models import CacheEntry, CacheExportSnapshot, ConversionStatus, DocumentStatus
from doc_organize.core.progress import CancelToken, ProgressEvent
from doc_organize.export import CACHE_SNAPSHOT_NAME, ExportStats, load_cache_entries, preview_project_zip, write_project_zip, zip_export
from doc_organize.projects import ProjectLayout


def _entry(file_path: str, status: DocumentStatus = DocumentStatus.NEW, **kwargs: object) -> CacheEntry:
    return CacheEntry(
        file_path=file_path,
        sha256_hash="a" * 64,
        timestamp=1_700_000_000.0,
        status=status,
        conversion_status=ConversionStatus.SUCCESS,
        **kwargs,  # type: ignore[arg-type]
    )


def _project(tmp_path: Path, state_root: Path | None = None) -> ProjectLayout:
    layout = ProjectLayout(tmp_path / "Proyecto", state_root=state_root)
    (layout.conversion_dir / "carpeta_b" / "img").mkdir(parents=True)
    (layout.conversion_dir / "carpeta_a").mkdir(parents=True)
    (layout.conversion_dir / "carpeta_b" / "informe.md").write_text("# Informe", encoding="utf-8")
    (layout.conversion_dir / "carpeta_b" / "informe.json").write_text('{"texto": "ñandú"}', encoding="utf-8")
    (layout.conversion_dir / "carpeta_b" / "img" / "figura.png").write_bytes(os.urandom(3000))
    (layout.conversion_dir / "carpeta_a" / "acta reunión.md").write_text("Acta", encoding="utf-8")
    layout.dedup_report_dir.mkdir(parents=True)
    layout.dedup_report.write_text(json.dumps({"groups": []}), encoding="utf-8")
    return layout


ENTRIES = [
    _entry("/repo/b.pdf", DocumentStatus.MODIFIED),
    _entry("/repo/a.pdf", DocumentStatus.NEW),
    _entry("/repo/c ñ.pdf", DocumentStatus.UNCHANGED),
]


def test_zip_contains_conversion_snapshot_and_dedup_report_in_stable_order(tmp_path) -> None:
    layout = _project(tmp_path)
    destination = tmp_path / "export.zip"

    write_project_zip(destination, ENTRIES, layout=layout)

    with zipfile.ZipFile(destination) as zip_file:
        assert zip_file.namelist() == [
            "Conversión/carpeta_a/acta reunión.md",
            "Conversión/carpeta_b/informe.json",
            "Conversión/carpeta_b/informe.md",
            "Conversión/carpeta_b/img/figura.png",
            CACHE_SNAPSHOT_NAME,
            "duplicados/DEDUP_REPORT.json",
        ]
        assert zip_file.read("Conversión/carpeta_b/img/figura.png") == (layout.conversion_dir / "carpeta_b" / "img" / "figura.png").read_bytes()
        assert zip_file.testzip() is None
        snapshot = CacheExportSnapshot.model_validate_json(zip_file.read(CACHE_SNAPSHOT_NAME))

    assert snapshot.total_entries == 3
    assert [entry.file_path for entry in snapshot.entries] == ["/repo/a.pdf", "/repo/b.pdf", "/repo/c ñ.pdf"]
    assert snapshot.new_files == ["/repo/a.pdf"]
    assert snapshot.modified_files == ["/repo/b.pdf"]
    assert snapshot.unchanged_files == ["/repo/c ñ.pdf"]
    assert snapshot.entries[0] == ENTRIES[1]


def test_snapshot_json_matches_pydantic_serialization(tmp_path) -> None:
    """El JSON por trozos es el mismo documento que `CacheExportSnapshot.model_dump_json(indent=2)`."""
    buffer = io.BytesIO()
    write_project_zip(buffer, ENTRIES, conversion_dir=tmp_path / "no_existe")

    raw = zipfile.ZipFile(buffer).read(CACHE_SNAPSHOT_NAME).decode("utf-8")
    snapshot = CacheExportSnapshot.model_validate_json(raw)

    assert raw == snapshot.model_dump_json(indent=2)


def test_snapshot_json_with_no_entries_is_valid(tmp_path) -> None:
    buffer = io.BytesIO()
    write_project_zip(buffer, [], conversion_dir=tmp_path)

    raw = zipfile.ZipFile(buffer).read(CACHE_SNAPSHOT_NAME).decode("utf-8")

    assert json.loads(raw)["entries"] == []
    assert raw == CacheExportSnapshot.model_validate_json(raw).model_dump_json(indent=2)


@pytest.mark.parametrize("with_state_root", [False, True])
def test_preview_matches_zip_contents_exactly(tmp_path, with_state_root) -> None:
    layout = _project(tmp_path, state_root=tmp_path / "estado" if with_state_root else None)
    destination = tmp_path / "export.zip"

    preview = preview_project_zip(ENTRIES, layout=layout)
    written = write_project_zip(destination, ENTRIES, layout=layout)

    with zipfile.ZipFile(destination) as zip_file:
        infos = zip_file.infolist()
    assert preview == written == ExportStats(file_count=len(infos), total_size_bytes=sum(info.file_size for info in infos))
    assert preview.file_count == 6


def test_preview_is_independent_of_microseconds(tmp_path, monkeypatch) -> None:
    """`isoformat()` omite los microsegundos si valen 0: la marca de tiempo tiene longitud fija."""
    timestamps = iter(["2026-11-01T10:00:00.000000+00:00", "2026-11-01T10:00:00.123456+00:00"])
    monkeypatch.setattr(zip_export, "_export_timestamp", lambda: next(timestamps))

    assert preview_project_zip(ENTRIES, conversion_dir=tmp_path) == write_project_zip(io.BytesIO(), ENTRIES, conversion_dir=tmp_path)


def test_explicit_paths_are_equivalent_to_layout(tmp_path) -> None:
    layout = _project(tmp_path)

    by_layout = preview_project_zip(ENTRIES, layout=layout)
    by_paths = preview_project_zip(ENTRIES, conversion_dir=layout.conversion_dir, dedup_report=layout.dedup_report)

    assert by_layout == by_paths


def test_layout_and_explicit_paths_are_exclusive(tmp_path) -> None:
    with pytest.raises(ValueError, match="no ambos"):
        preview_project_zip([], layout=ProjectLayout(tmp_path), conversion_dir=tmp_path)


def test_state_root_puts_dedup_report_under_duplicados(tmp_path) -> None:
    layout = _project(tmp_path, state_root=tmp_path / "estado")
    buffer = io.BytesIO()

    write_project_zip(buffer, [], layout=layout)

    assert "duplicados/DEDUP_REPORT.json" in zipfile.ZipFile(buffer).namelist()


def test_never_scanned_project_exports_only_empty_snapshot(tmp_path) -> None:
    layout = ProjectLayout(tmp_path / "vacio")
    buffer = io.BytesIO()

    stats = write_project_zip(buffer, [], layout=layout)

    assert stats.file_count == 1
    assert json.loads(zipfile.ZipFile(buffer).read(CACHE_SNAPSHOT_NAME))["total_entries"] == 0


class _NonSeekable(io.RawIOBase):
    """Flujo de solo escritura sin `seek` (p. ej. una respuesta HTTP en streaming)."""

    def __init__(self) -> None:
        self.data = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, chunk) -> int:  # type: ignore[override]
        self.data.extend(chunk)
        return len(chunk)


def test_zip_streams_to_non_seekable_binary_file(tmp_path) -> None:
    layout = _project(tmp_path)
    stream = _NonSeekable()

    stats = write_project_zip(stream, ENTRIES, layout=layout)  # type: ignore[arg-type]

    with zipfile.ZipFile(io.BytesIO(bytes(stream.data))) as zip_file:
        assert zip_file.testzip() is None
        assert len(zip_file.infolist()) == stats.file_count == 6


def test_files_are_copied_in_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(zip_export, "_CHUNK_SIZE", 7)
    layout = _project(tmp_path)
    buffer = io.BytesIO()

    write_project_zip(buffer, [], layout=layout)

    original = (layout.conversion_dir / "carpeta_b" / "img" / "figura.png").read_bytes()
    assert zipfile.ZipFile(buffer).read("Conversión/carpeta_b/img/figura.png") == original


@pytest.mark.asyncio
async def test_several_caches_are_exported_together(tmp_path) -> None:
    """doc_organize_web tiene una caché por carpeta de origen: el ZIP lleva la unión, ordenada."""
    cache_a, cache_b = tmp_path / "a" / "cache.db", tmp_path / "b" / "cache.db"
    cache_a.parent.mkdir()
    cache_b.parent.mkdir()
    async with CacheManager(cache_a) as cache:
        await cache.save_entries([_entry("/origen_a/uno.pdf"), _entry("/compartido.pdf", DocumentStatus.NEW)])
    async with CacheManager(cache_b) as cache:
        await cache.save_entries([_entry("/origen_b/dos.pdf", DocumentStatus.MODIFIED), _entry("/compartido.pdf", DocumentStatus.UNCHANGED)])

    entries = await load_cache_entries([cache_a, cache_b, tmp_path / "no_existe" / "cache.db"])
    buffer = io.BytesIO()
    write_project_zip(buffer, entries, conversion_dir=tmp_path / "Conversión")

    snapshot = CacheExportSnapshot.model_validate_json(zipfile.ZipFile(buffer).read(CACHE_SNAPSHOT_NAME))
    assert [entry.file_path for entry in snapshot.entries] == ["/compartido.pdf", "/origen_a/uno.pdf", "/origen_b/dos.pdf"]
    assert snapshot.unchanged_files == ["/compartido.pdf"]  # en una ruta repetida gana la última caché
    assert not (tmp_path / "no_existe").exists()  # una caché ausente no se crea


def test_progress_reports_every_file(tmp_path) -> None:
    layout = _project(tmp_path)
    events: list[ProgressEvent] = []

    write_project_zip(io.BytesIO(), ENTRIES, layout=layout, on_progress=events.append)

    assert [event.phase for event in events] == ["started", *["export"] * 6, "done"]
    assert {event.operation for event in events} == {"export"}
    assert {event.total for event in events} == {6}
    assert [event.processed for event in events] == [0, 1, 2, 3, 4, 5, 6, 6]
    assert events[5].current == CACHE_SNAPSHOT_NAME


def test_failing_progress_callback_does_not_stop_export(tmp_path) -> None:
    def _boom(_: ProgressEvent) -> None:
        raise RuntimeError("callback roto")

    stats = write_project_zip(io.BytesIO(), ENTRIES, layout=_project(tmp_path), on_progress=_boom)

    assert stats.file_count == 6


def test_cancel_deletes_partial_zip_and_raises(tmp_path) -> None:
    layout = _project(tmp_path)
    destination = tmp_path / "export.zip"
    token = CancelToken()

    def _cancel_after_first_file(event: ProgressEvent) -> None:
        if event.phase == "export":
            token.cancel()

    with pytest.raises(OperationCancelledError):
        write_project_zip(destination, ENTRIES, layout=layout, on_progress=_cancel_after_first_file, cancel_token=token)

    assert not destination.exists()


class _CountingReader(io.BufferedReader):
    """Lector que cancela el token al tercer bloque leído."""

    token: CancelToken
    reads = 0

    def read(self, size: int | None = -1) -> bytes:
        type(self).reads += 1
        if type(self).reads == 3:
            self.token.cancel()
        return super().read(size)


def test_cancel_inside_a_file_stops_between_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(zip_export, "_CHUNK_SIZE", 100)
    layout = _project(tmp_path)
    token = CancelToken()
    monkeypatch.setattr(_CountingReader, "token", token, raising=False)
    monkeypatch.setattr(_CountingReader, "reads", 0)
    original_open = Path.open

    def _counting_open(self: Path, mode: str = "r", *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if self.name == "figura.png":
            return _CountingReader(io.FileIO(self, "rb"))
        return original_open(self, mode, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", _counting_open)
    destination = tmp_path / "export.zip"

    with pytest.raises(OperationCancelledError):
        write_project_zip(destination, [], layout=layout, cancel_token=token)

    assert _CountingReader.reads == 3  # 3 000 bytes en bloques de 100: paró sin leer el resto
    assert not destination.exists()


def test_cancelled_before_start_writes_nothing(tmp_path) -> None:
    token = CancelToken()
    token.cancel()
    destination = tmp_path / "export.zip"

    with pytest.raises(OperationCancelledError):
        write_project_zip(destination, ENTRIES, layout=_project(tmp_path), cancel_token=token)

    assert not destination.exists()


def test_destination_inside_conversion_dir_is_rejected(tmp_path) -> None:
    layout = _project(tmp_path)
    destination = layout.conversion_dir / "export.zip"

    with pytest.raises(InvalidPathError):
        write_project_zip(destination, [], layout=layout)

    assert not destination.exists()


def test_symlinks_in_conversion_dir_are_not_followed(tmp_path) -> None:
    layout = _project(tmp_path)
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto.txt").write_text("no debe salir", encoding="utf-8")
    try:
        (layout.conversion_dir / "enlace.txt").symlink_to(outside / "secreto.txt")
        (layout.conversion_dir / "carpeta_enlace").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Sin permiso para crear enlaces simbólicos")
    buffer = io.BytesIO()

    stats = write_project_zip(buffer, [], layout=layout)

    names = zipfile.ZipFile(buffer).namelist()
    assert not any("enlace" in name or "secreto" in name for name in names)
    assert preview_project_zip([], layout=layout) == stats
