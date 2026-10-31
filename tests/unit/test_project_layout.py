"""`ProjectLayout` y rutas de estado separables de las salidas (L-4, L-5; huecos G4/G5 de doc_organize_web)."""

import re

from pathlib import Path

import pytest

import doc_organize

from doc_organize import ProjectLayout, ScanCommand, ScanOptions
from doc_organize.core.constants import (
    CONVERSION_FOLDER_NAME,
    DEDUP_HISTORY_JSONL_NAME,
    DEDUP_REPORT_JSON_NAME,
    DEFAULT_CACHE_DB_NAME,
    DUPLICATES_FOLDER_NAME,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_ERRORS_HISTORY_JSONL_NAME,
    SCAN_FOLDERS_JSON_NAME,
    SCAN_HISTORY_FOLDER_NAME,
    SCAN_HISTORY_JSONL_NAME,
)
from doc_organize.core.models import DedupEventType, Project, ScanEventType
from doc_organize.dedup import DeduplicationManager
from doc_organize.projects import ProjectHistoryCleaner, ScannedFoldersStore

SRC = Path(doc_organize.__file__).parent


def test_default_layout_keeps_legacy_paths(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)

    assert layout.conversion_dir == tmp_path / CONVERSION_FOLDER_NAME
    assert layout.duplicates_dir == tmp_path / DUPLICATES_FOLDER_NAME
    assert layout.cache_db == tmp_path / DEFAULT_CACHE_DB_NAME
    assert layout.folders_json == tmp_path / SCAN_FOLDERS_JSON_NAME
    assert layout.scanned_folders_json == tmp_path / "scanned_folders.json"
    assert layout.scan_errors_log == tmp_path / SCAN_ERRORS_FOLDER_NAME / SCAN_ERRORS_HISTORY_JSONL_NAME
    assert layout.scan_history_log == tmp_path / SCAN_HISTORY_FOLDER_NAME / SCAN_HISTORY_JSONL_NAME
    assert layout.dedup_report == tmp_path / DUPLICATES_FOLDER_NAME / DEDUP_REPORT_JSON_NAME
    assert layout.dedup_history == tmp_path / DUPLICATES_FOLDER_NAME / DEDUP_HISTORY_JSONL_NAME
    assert layout.separate_state is False


def test_separate_state_root_moves_only_state(tmp_path: Path) -> None:
    output, state = tmp_path / "salidas", tmp_path / "estado"
    layout = ProjectLayout(output, state_root=state)

    outputs = [layout.conversion_dir, layout.duplicates_dir, layout.site_dir]
    states = [
        layout.cache_db,
        layout.folders_json,
        layout.scanned_folders_json,
        layout.scan_errors_log,
        layout.scan_history_log,
        layout.dedup_report,
        layout.dedup_history,
    ]

    assert all(path.is_relative_to(output) for path in outputs)
    assert all(path.is_relative_to(state) for path in states)
    assert layout.separate_state is True


def test_for_project_uses_root_path(tmp_path: Path) -> None:
    project = Project(name="P", root_path=str(tmp_path), created_at="2026-10-31T00:00:00+00:00")

    assert ProjectLayout.for_project(project).cache_db == tmp_path / DEFAULT_CACHE_DB_NAME


@pytest.mark.asyncio
async def test_scan_and_dedup_with_separate_state_do_not_cross_files(tmp_path: Path) -> None:
    source = tmp_path / "origen"
    source.mkdir()
    layout = ProjectLayout(tmp_path / "salidas", state_root=tmp_path / "estado")

    scan_events = [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(source)],
            output_dir=layout.conversion_dir,
            cache_db=layout.cache_db,
            folders_json=layout.folders_json,
            error_log_path=layout.scan_errors_log,
            history_log_path=layout.scan_history_log,
            options=ScanOptions(use_ocr=False),
        )
    ]
    dedup_events = [
        event
        async for event in ScanCommand().deduplicate_streaming(
            [str(source)], layout.duplicates_dir, layout.folders_json, report_dir=layout.dedup_report_dir
        )
    ]

    assert scan_events[-1].event is ScanEventType.COMPLETED
    assert dedup_events[-1].event is DedupEventType.COMPLETED
    assert layout.cache_db.exists()
    assert layout.scan_history_log.exists()
    assert layout.dedup_report.exists()
    assert layout.dedup_history.exists()
    state_names = {DEFAULT_CACHE_DB_NAME, SCAN_FOLDERS_JSON_NAME, DEDUP_REPORT_JSON_NAME, DEDUP_HISTORY_JSONL_NAME}
    assert not {p.name for p in (tmp_path / "salidas").rglob("*")} & state_names
    assert not any(p.name == CONVERSION_FOLDER_NAME for p in (tmp_path / "estado").rglob("*"))


@pytest.mark.asyncio
async def test_resolve_duplicates_writes_report_in_report_dir(tmp_path: Path) -> None:
    report = await DeduplicationManager().resolve_duplicates([], tmp_path / "duplicados", report_dir=tmp_path / "estado" / "duplicados")

    assert Path(report.audit_json_path) == tmp_path / "estado" / "duplicados" / DEDUP_REPORT_JSON_NAME
    assert not (tmp_path / "duplicados" / DEDUP_REPORT_JSON_NAME).exists()


@pytest.mark.asyncio
async def test_scanned_folders_store_accepts_explicit_path(tmp_path: Path) -> None:
    project = Project(name="P", root_path=str(tmp_path / "salidas"), created_at="2026-10-31T00:00:00+00:00")
    (tmp_path / "salidas").mkdir()
    folder = tmp_path / "origen"
    folder.mkdir()
    registry = tmp_path / "estado" / "scanned_folders.json"
    registry.parent.mkdir()

    await ScannedFoldersStore(registry_path=registry).add_folder(project, str(folder))

    assert registry.exists()
    assert not (tmp_path / "salidas" / "scanned_folders.json").exists()


@pytest.mark.asyncio
async def test_history_cleaner_also_clears_separate_state(tmp_path: Path) -> None:
    root, state = tmp_path / "salidas", tmp_path / "estado"
    root.mkdir()
    (state / "historial_escaneo").mkdir(parents=True)
    (state / "cache.db").write_text("x", encoding="utf-8")
    (root / "Conversión").mkdir()
    project = Project(name="P", root_path=str(root), created_at="2026-10-31T00:00:00+00:00")

    await ProjectHistoryCleaner().clear(project, state_root=state)

    assert [p.name for p in root.iterdir()] == ["project.json"]
    assert list(state.iterdir()) == []


_JOIN = re.compile(
    r"/\s*(DEFAULT_CACHE_DB_NAME|SCAN_FOLDERS_JSON_NAME|DUPLICATES_FOLDER_NAME|CONVERSION_FOLDER_NAME"
    r"|SCAN_ERRORS_FOLDER_NAME|SCAN_HISTORY_FOLDER_NAME)\b"
)


def test_only_project_layout_builds_project_paths() -> None:
    """Fuera de `web/` (congelada, se retira en 1.0.0) ningún módulo construye estas rutas por su cuenta (L-4)."""
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "web" not in path.relative_to(SRC).parts
        and path.name not in {"layout.py", "constants.py"}
        and _JOIN.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
