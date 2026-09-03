"""Tests de `doc_organize.scan.scan_history_store` (histórico de duración de
ejecuciones de escaneo, `historial_escaneo/SCAN_HISTORY.jsonl`)."""

import json

import pytest

from doc_organize.core.models import ScanRunReport
from doc_organize.scan.scan_history_store import append_scan_run, list_scan_runs


def _report(scan_run_id: str, *, duration: float = 1.5, scanned: int = 3, completed: bool = True) -> ScanRunReport:
    return ScanRunReport(
        scan_run_id=scan_run_id,
        started_at="2026-08-01T10:00:00+00:00",
        finished_at="2026-08-01T10:00:01+00:00",
        duration_seconds=duration,
        total_scanned=scanned,
        completed=completed,
    )


def test_list_scan_runs_returns_empty_list_when_file_missing(tmp_path) -> None:
    assert list_scan_runs(tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl") == []


@pytest.mark.asyncio
async def test_append_scan_run_creates_folder_and_writes_line(tmp_path) -> None:
    history_path = tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl"

    await append_scan_run(history_path, _report("run-1"))

    assert history_path.is_file()
    line = json.loads(history_path.read_text(encoding="utf-8").strip())
    assert line["scan_run_id"] == "run-1"
    assert line["duration_seconds"] == 1.5
    assert line["total_scanned"] == 3
    assert line["completed"] is True


@pytest.mark.asyncio
async def test_append_scan_run_is_append_only(tmp_path) -> None:
    history_path = tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl"

    await append_scan_run(history_path, _report("run-1"))
    await append_scan_run(history_path, _report("run-2"))

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_list_scan_runs_returns_most_recent_first(tmp_path) -> None:
    history_path = tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl"

    await append_scan_run(history_path, _report("run-1"))
    await append_scan_run(history_path, _report("run-2"))

    runs = list_scan_runs(history_path)

    assert [run.scan_run_id for run in runs] == ["run-2", "run-1"]


@pytest.mark.asyncio
async def test_list_scan_runs_includes_incomplete_runs(tmp_path) -> None:
    history_path = tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl"

    await append_scan_run(history_path, _report("run-cancelado", completed=False))

    runs = list_scan_runs(history_path)

    assert runs[0].completed is False


def test_list_scan_runs_ignores_corrupted_line(tmp_path) -> None:
    history_path = tmp_path / "historial_escaneo" / "SCAN_HISTORY.jsonl"
    history_path.parent.mkdir(parents=True)
    valid = _report("run-valido").model_dump_json()
    history_path.write_text("{linea corrupta\n" + valid + "\n", encoding="utf-8")

    runs = list_scan_runs(history_path)

    assert [run.scan_run_id for run in runs] == ["run-valido"]
