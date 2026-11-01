"""Excel de caché y de errores de escaneo (L-7, G8): contenido, fórmulas escapadas, cancelación y openpyxl ausente."""

import io
import json
import sys
import tempfile

from pathlib import Path

import openpyxl
import pytest

from doc_organize.core.exceptions import MissingDependencyError, OperationCancelledError
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus, ScanErrorEntry, ScanErrorReport
from doc_organize.core.progress import CancelToken, ProgressEvent
from doc_organize.export import load_scan_error_history, write_cache_xlsx, write_scan_errors_xlsx
from doc_organize.export.xlsx_export import (
    CACHE_COLUMNS,
    SCAN_ERRORS_CURRENT_COLUMNS,
    SCAN_ERRORS_HISTORY_COLUMNS,
)


def _entry(file_path: str, conversion_status: ConversionStatus = ConversionStatus.SUCCESS, **kwargs: object) -> CacheEntry:
    return CacheEntry(
        file_path=file_path,
        sha256_hash="f" * 64,
        timestamp=1_700_000_000.0,
        status=DocumentStatus.NEW,
        conversion_status=conversion_status,
        **kwargs,  # type: ignore[arg-type]
    )


def _rows(source: Path | io.BytesIO, sheet: str) -> list[tuple[object, ...]]:
    workbook = openpyxl.load_workbook(source)
    return [tuple(row) for row in workbook[sheet].iter_rows(values_only=True)]


def test_cache_xlsx_has_all_entries_sorted_with_full_hash(tmp_path) -> None:
    destination = tmp_path / "cache.xlsx"

    rows_written = write_cache_xlsx(destination, [_entry("/repo/z.pdf"), _entry("/repo/docs/a.pdf", conversion_status=ConversionStatus.ERROR)])

    rows = _rows(destination, "Cache")
    assert rows_written == 2
    assert rows[0] == CACHE_COLUMNS
    assert [row[2] for row in rows[1:]] == ["/repo/docs/a.pdf", "/repo/z.pdf"]
    assert rows[1][0] == "a.pdf"
    assert rows[1][3] == "f" * 64
    assert rows[1][4:7] == ("new", "error", "2023-11-14T22:13:20+00:00")
    assert openpyxl.load_workbook(destination)["Cache"]["A1"].font.bold


def test_cache_xlsx_without_conversion_status_leaves_cell_empty(tmp_path) -> None:
    entry = _entry("/repo/a.pdf").model_copy(update={"conversion_status": None})
    buffer = io.BytesIO()

    write_cache_xlsx(buffer, [entry])

    assert _rows(buffer, "Cache")[1][5] is None


@pytest.mark.parametrize("dangerous", ['=HYPERLINK("x")', "=1+2*3", "+1+1", "-2", "@SUM(A1)", "\tTAB", "\rCR"])
def test_formula_cells_are_escaped_in_every_text_column(tmp_path, dangerous) -> None:
    error_entry = _entry(f"/repo/{dangerous}", conversion_status=ConversionStatus.ERROR, error_message=dangerous)
    report = ScanErrorReport(
        scan_run_id="run",
        timestamp="2026-11-01T10:00:00+00:00",
        total_scanned=1,
        entries=[ScanErrorEntry(file_path=dangerous, error_message=dangerous, error_retry_count=1)],
    )
    cache_xlsx, errors_xlsx = tmp_path / "cache.xlsx", tmp_path / "errores.xlsx"

    write_cache_xlsx(cache_xlsx, [error_entry])
    write_scan_errors_xlsx(errors_xlsx, [error_entry], [report])

    escaped = f"'{dangerous}"
    assert _rows(cache_xlsx, "Cache")[1][0] == escaped
    assert _rows(errors_xlsx, "Estado actual")[1][0] == escaped
    assert _rows(errors_xlsx, "Estado actual")[1][3] == escaped
    history = _rows(errors_xlsx, "Histórico")[1]
    assert history[2] == history[4] == history[5] == escaped
    for path in (cache_xlsx, errors_xlsx):
        for sheet in openpyxl.load_workbook(path).worksheets:
            assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)


def test_control_characters_are_removed_instead_of_failing(tmp_path) -> None:
    entry = _entry("/repo/roto.pdf", conversion_status=ConversionStatus.ERROR, error_message="fallo\x00\x07 en página\x1f 3")

    write_scan_errors_xlsx(tmp_path / "errores.xlsx", [entry], [])

    assert _rows(tmp_path / "errores.xlsx", "Estado actual")[1][3] == "fallo en página 3"


def test_scan_errors_xlsx_has_current_and_history_sheets(tmp_path) -> None:
    entries = [
        _entry("/repo/ok.pdf"),
        _entry("/repo/roto.pdf", conversion_status=ConversionStatus.ERROR, error_message="Documento cifrado", error_retry_count=1),
        _entry("/repo/aaa.pdf", conversion_status=ConversionStatus.ERROR, error_message="Otra", error_retry_count=3),
    ]
    history = [
        ScanErrorReport(
            scan_run_id="run-1",
            timestamp="2026-08-01T10:00:00+00:00",
            total_scanned=5,
            entries=[ScanErrorEntry(file_path="/repo/viejo.pdf", error_message="Error previo", error_retry_count=3, capped=True)],
        )
    ]
    destination = tmp_path / "errores.xlsx"

    assert write_scan_errors_xlsx(destination, entries, history) == 3

    assert openpyxl.load_workbook(destination).sheetnames == ["Estado actual", "Histórico"]
    current = _rows(destination, "Estado actual")
    assert current[0] == SCAN_ERRORS_CURRENT_COLUMNS
    assert current[1] == ("aaa.pdf", str(Path("/repo")), "/repo/aaa.pdf", "Otra", 3, "Sí")
    assert current[2][0] == "roto.pdf" and current[2][5] == "No"
    rows = _rows(destination, "Histórico")
    assert rows[0] == SCAN_ERRORS_HISTORY_COLUMNS
    assert rows[1] == ("run-1", "2026-08-01T10:00:00+00:00", "viejo.pdf", str(Path("/repo")), "/repo/viejo.pdf", "Error previo", 3, "Sí")


def test_empty_scan_errors_xlsx_has_headers_only() -> None:
    buffer = io.BytesIO()

    assert write_scan_errors_xlsx(buffer, [], []) == 0

    assert _rows(buffer, "Estado actual") == [SCAN_ERRORS_CURRENT_COLUMNS]
    assert _rows(buffer, "Histórico") == [SCAN_ERRORS_HISTORY_COLUMNS]


def test_history_from_several_logs_is_merged_newest_first(tmp_path) -> None:
    def _report(run: str, timestamp: str) -> str:
        return json.dumps({"scan_run_id": run, "timestamp": timestamp, "total_scanned": 1, "entries": []})

    log_a, log_b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    log_a.write_text(
        _report("a1", "2026-01-01T00:00:00+00:00") + "\n{corrupta\n\n" + _report("a2", "2026-03-01T00:00:00+00:00") + "\n", encoding="utf-8"
    )
    log_b.write_text(_report("b1", "2026-02-01T00:00:00+00:00") + "\n", encoding="utf-8")

    history = load_scan_error_history([log_a, log_b, tmp_path / "no_existe.jsonl"])

    assert [report.scan_run_id for report in history] == ["a2", "b1", "a1"]


def test_progress_reports_rows(tmp_path) -> None:
    events: list[ProgressEvent] = []

    write_cache_xlsx(io.BytesIO(), [_entry("/a.pdf"), _entry("/b.pdf")], on_progress=events.append)

    assert [(event.phase, event.processed, event.total) for event in events] == [
        ("started", 0, 2),
        ("export", 1, 2),
        ("export", 2, 2),
        ("done", 2, 2),
    ]


def test_cancel_deletes_partial_xlsx_and_openpyxl_temporaries(tmp_path, monkeypatch) -> None:
    temporaries = tmp_path / "tmp"
    temporaries.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporaries))
    destination = tmp_path / "cache.xlsx"
    token = CancelToken()

    def _cancel_after_first_row(event: ProgressEvent) -> None:
        if event.phase == "export":
            token.cancel()

    with pytest.raises(OperationCancelledError):
        write_cache_xlsx(destination, [_entry("/a.pdf"), _entry("/b.pdf")], on_progress=_cancel_after_first_row, cancel_token=token)

    assert not destination.exists()
    assert list(temporaries.iterdir()) == []


def test_missing_openpyxl_raises_typed_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    with pytest.raises(MissingDependencyError) as excinfo:
        write_cache_xlsx(tmp_path / "cache.xlsx", [])

    assert excinfo.value.extra == "export"
    assert "doc_organize[export]" in str(excinfo.value)
    assert not (tmp_path / "cache.xlsx").exists()
