"""Tests unitarios (sin I/O) de `ScanCommand._collect_stale_error_paths()`.

El resto de `ScanCommand` se cubre de extremo a extremo vía `test_web_scan.py`
(orquesta escaneo real + Docling), pero esta función es pura — no necesita eso.
"""

import pytest

from doc_organize.converter import DocumentConverter
from doc_organize.core.constants import MAX_AUTO_ERROR_RETRIES
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentMetadata, DocumentStatus
from doc_organize.scan import ScanCommand


def _entry(file_path: str, conversion_status: ConversionStatus | None, error_retry_count: int = 0) -> CacheEntry:
    return CacheEntry(
        file_path=file_path,
        sha256_hash="hash",
        timestamp=1.0,
        status=DocumentStatus.UNCHANGED,
        conversion_status=conversion_status,
        error_retry_count=error_retry_count,
    )


def _doc(file_path: str) -> DocumentMetadata:
    return DocumentMetadata(
        full_path=file_path,
        display_name=file_path.rsplit("/", 1)[-1],
        extension="pdf",
        size_bytes=10,
        modified_time=1.0,
        sha256_hash="hash",
    )


def test_collect_stale_error_paths_includes_error_entry_still_on_disk() -> None:
    cached_entries = {"/repo/roto.pdf": _entry("/repo/roto.pdf", ConversionStatus.ERROR)}
    docs_by_path = {"/repo/roto.pdf": _doc("/repo/roto.pdf")}

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths=set())

    assert retryable == {"/repo/roto.pdf"}
    assert capped == set()


def test_collect_stale_error_paths_excludes_entry_whose_file_no_longer_exists() -> None:
    cached_entries = {"/repo/borrado.pdf": _entry("/repo/borrado.pdf", ConversionStatus.ERROR)}
    docs_by_path: dict[str, DocumentMetadata] = {}  # ya no aparece en el escaneo actual

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths=set())

    assert retryable == set()
    assert capped == set()


def test_collect_stale_error_paths_excludes_entry_already_in_to_process_paths() -> None:
    """Un fichero ERROR que además cambió de hash ya está en `to_process_paths`
    (clasificado `modified`) — no debe duplicarse en el resultado."""
    cached_entries = {"/repo/modificado.pdf": _entry("/repo/modificado.pdf", ConversionStatus.ERROR)}
    docs_by_path = {"/repo/modificado.pdf": _doc("/repo/modificado.pdf")}

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths={"/repo/modificado.pdf"})

    assert retryable == set()
    assert capped == set()


def test_collect_stale_error_paths_ignores_non_error_conversion_status() -> None:
    cached_entries = {
        "/repo/ok.pdf": _entry("/repo/ok.pdf", ConversionStatus.SUCCESS),
        "/repo/pendiente.pdf": _entry("/repo/pendiente.pdf", ConversionStatus.OCR_PENDING),
        "/repo/sin_estado.pdf": _entry("/repo/sin_estado.pdf", None),
    }
    docs_by_path = {path: _doc(path) for path in cached_entries}

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths=set())

    assert retryable == set()
    assert capped == set()


def test_collect_stale_error_paths_below_limit_is_retryable() -> None:
    cached_entries = {"/repo/roto.pdf": _entry("/repo/roto.pdf", ConversionStatus.ERROR, error_retry_count=MAX_AUTO_ERROR_RETRIES - 1)}
    docs_by_path = {"/repo/roto.pdf": _doc("/repo/roto.pdf")}

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths=set())

    assert retryable == {"/repo/roto.pdf"}
    assert capped == set()


def test_collect_stale_error_paths_at_limit_is_capped_not_retried() -> None:
    """Al alcanzar `MAX_AUTO_ERROR_RETRIES` fallos consecutivos, deja de
    reintentarse automáticamente — pero la ruta se sigue devolviendo (como
    `capped`), no se descarta en silencio (ver `ScanSummary.error_retries_capped`)."""
    cached_entries = {"/repo/irrecuperable.pdf": _entry("/repo/irrecuperable.pdf", ConversionStatus.ERROR, error_retry_count=MAX_AUTO_ERROR_RETRIES)}
    docs_by_path = {"/repo/irrecuperable.pdf": _doc("/repo/irrecuperable.pdf")}

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths=set())

    assert retryable == set()
    assert capped == {"/repo/irrecuperable.pdf"}


@pytest.mark.asyncio
async def test_delete_orphaned_outputs_logs_warning_on_rmtree_failure(monkeypatch, tmp_path, caplog) -> None:
    """AUDIT_CODE: si borrar `img/<stem>/` de un huérfano falla, se loguea un warning
    y el resto del force-rescan sigue (no se propaga la excepción)."""
    import doc_organize.scan.scan_command as scan_command_module

    output_dir = tmp_path / "Conversión"
    source_path = str(tmp_path / "input" / "informe.pdf")

    markdown_path, json_path = DocumentConverter.resolve_output_paths(source_path, output_dir)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("contenido", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")
    images_dir = DocumentConverter.resolve_images_dir(markdown_path)
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "image_000000_abc.png").write_bytes(b"fake-png")

    def _boom(path: object) -> None:
        raise OSError("simulated permission denied")

    monkeypatch.setattr(scan_command_module.shutil, "rmtree", _boom)

    with caplog.at_level("WARNING"):
        await ScanCommand._delete_orphaned_outputs({source_path}, output_dir)  # no debe lanzar

    assert not markdown_path.exists()
    assert not json_path.exists()
    assert images_dir.exists()  # no se pudo borrar, pero el flujo no se rompe
    assert any("simulated permission denied" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_delete_orphaned_outputs_removes_images_dir(tmp_path) -> None:
    """AUDIT_CODE: `--force` debe borrar tambien `img/<stem>/` de un documento
    huerfano, no solo su `.md`/`.json` — antes quedaba huerfana para siempre."""
    output_dir = tmp_path / "Conversión"
    source_path = str(tmp_path / "input" / "informe.pdf")

    markdown_path, json_path = DocumentConverter.resolve_output_paths(source_path, output_dir)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("contenido", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")
    images_dir = DocumentConverter.resolve_images_dir(markdown_path)
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "image_000000_abc.png").write_bytes(b"fake-png")

    await ScanCommand._delete_orphaned_outputs({source_path}, output_dir)

    assert not markdown_path.exists()
    assert not json_path.exists()
    assert not images_dir.exists()


def test_collect_stale_error_paths_above_limit_is_capped_not_retried() -> None:
    cached_entries = {
        "/repo/irrecuperable.pdf": _entry("/repo/irrecuperable.pdf", ConversionStatus.ERROR, error_retry_count=MAX_AUTO_ERROR_RETRIES + 5)
    }
    docs_by_path = {"/repo/irrecuperable.pdf": _doc("/repo/irrecuperable.pdf")}

    retryable, capped = ScanCommand._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths=set())

    assert retryable == set()
    assert capped == {"/repo/irrecuperable.pdf"}
