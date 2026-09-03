"""Tests unitarios (sin I/O) de `ScanCommand._collect_stale_error_paths()`.

El resto de `ScanCommand` se cubre de extremo a extremo vía `test_web_scan.py`
(orquesta escaneo real + Docling), pero esta función es pura — no necesita eso.
"""

import pytest

import doc_organize.scan.scan_command as scan_command_module

from doc_organize.converter import DocumentConverter
from doc_organize.core.constants import MAX_AUTO_ERROR_RETRIES
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentMetadata, DocumentStatus, ScanErrorEntry
from doc_organize.scan import ScanCommand
from doc_organize.scan.scan_history_store import list_scan_runs
from doc_organize.scanner import DocumentScanner


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


# ===== `history_log_path` (histórico de duración de ejecuciones): camino de aborto
# y tolerancia a fallos de la propia escritura (AUDIT_CODE, sesión de tiempos de
# escaneo) =====


@pytest.mark.asyncio
async def test_run_streaming_persists_completed_false_on_pipeline_exception(tmp_path, monkeypatch) -> None:
    """Una excepción real durante el pipeline (aquí, en el descubrimiento de
    ficheros) debe seguir propagándose al llamador, pero antes debe quedar
    registrada en `history_log_path` con `completed=False` -- es el requisito
    explícito de "runs incompletos" del PLAN de esta funcionalidad, y no tenía
    ningún test que lo ejercitara a través de `ScanCommand` (solo a través del
    store/plantillas con JSONL escrito a mano)."""

    async def _boom(self, paths, include_audio_video=False, exclude_dir=None):
        raise RuntimeError("fallo simulado de escaneo")

    monkeypatch.setattr(DocumentScanner, "scan_folders", _boom)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    history_path = tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl"

    with pytest.raises(RuntimeError, match="fallo simulado de escaneo"):
        async for _event in ScanCommand().run_streaming(
            paths=[str(input_dir)],
            output_dir=tmp_path / "Conversión",
            cache_db=tmp_path / "cache.db",
            folders_json=tmp_path / "folders.json",
            use_ocr=False,
            use_gpu=False,
            history_log_path=history_path,
        ):
            pass

    runs = list_scan_runs(history_path)
    assert len(runs) == 1
    assert runs[0].completed is False
    assert runs[0].total_scanned == 0
    assert runs[0].duration_seconds > 0


@pytest.mark.asyncio
async def test_run_streaming_completes_even_if_persisting_history_fails(tmp_path, monkeypatch, caplog) -> None:
    """Un fallo al escribir `history_log_path` (permiso denegado, disco lleno...)
    es telemetría opcional -- no debe abortar un escaneo que por lo demás
    termina con éxito ni impedir que el cliente reciba el evento `completed`."""

    async def _raise_os_error(history_log_path, report):
        raise OSError("simulated disk full")

    monkeypatch.setattr(scan_command_module, "append_scan_run", _raise_os_error)

    input_dir = tmp_path / "input"
    input_dir.mkdir()  # carpeta vacia: sin documentos que convertir, rapido

    with caplog.at_level("WARNING"):
        events = [
            event
            async for event in ScanCommand().run_streaming(
                paths=[str(input_dir)],
                output_dir=tmp_path / "Conversión",
                cache_db=tmp_path / "cache.db",
                folders_json=tmp_path / "folders.json",
                use_ocr=False,
                use_gpu=False,
                history_log_path=tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl",
            )
        ]

    assert events[-1].event.value == "completed"
    assert any("simulated disk full" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_run_streaming_completes_even_if_persisting_error_report_fails(tmp_path, monkeypatch, caplog) -> None:
    """Mismo criterio que `test_run_streaming_completes_even_if_persisting_history_fails`,
    aplicado a `error_log_path`/`_persist_error_report` (AUDIT_CODE, ronda de
    consistencia): un fallo real de I/O al escribir el histórico de errores de
    escaneo no debe abortar un escaneo que por lo demás termina con éxito."""

    # Se fuerza que haya "errores" que persistir sin necesitar una conversion
    # real fallida -- lo que se prueba aqui es la tolerancia a fallos de
    # _persist_error_report, no _collect_error_entries (ya cubierto por los
    # tests de _collect_stale_error_paths de arriba).
    monkeypatch.setattr(
        ScanCommand,
        "_collect_error_entries",
        staticmethod(
            lambda entries, capped_paths, cached_entries: [
                ScanErrorEntry(file_path="/repo/roto.pdf", error_message="fallo simulado", error_retry_count=1, capped=False)
            ]
        ),
    )

    input_dir = tmp_path / "input"
    input_dir.mkdir()  # carpeta vacia: sin documentos que convertir, rapido

    # Colision real de filesystem (no un mock): un fichero donde se espera una
    # carpeta hace que `error_log_path.parent.mkdir(parents=True, exist_ok=True)`
    # lance OSError de verdad, ejercitando el try/except de _persist_error_report
    # en vez de simular la excepcion desde fuera.
    blocked_path = tmp_path / "blocked_history"
    blocked_path.write_bytes(b"archivo, no carpeta")
    error_log_path = blocked_path / "SCAN_ERRORS_HISTORY.jsonl"

    with caplog.at_level("WARNING"):
        events = [
            event
            async for event in ScanCommand().run_streaming(
                paths=[str(input_dir)],
                output_dir=tmp_path / "Conversión",
                cache_db=tmp_path / "cache.db",
                folders_json=tmp_path / "folders.json",
                use_ocr=False,
                use_gpu=False,
                error_log_path=error_log_path,
            )
        ]

    assert events[-1].event.value == "completed"
    assert any("No se pudo persistir el histórico de errores de escaneo" in record.message for record in caplog.records)
