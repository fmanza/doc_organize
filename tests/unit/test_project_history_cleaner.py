"""Tests unitarios de ProjectHistoryCleaner (REQ-008, "vaciar histórico")."""

import json

from pathlib import Path

import pytest

from doc_organize.core.exceptions import ProjectError
from doc_organize.core.models import Project
from doc_organize.projects.project_history_cleaner import ProjectHistoryCleaner


def _make_project(root: Path) -> Project:
    return Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")


@pytest.mark.asyncio
async def test_clear_removes_all_content_and_regenerates_project_json(tmp_path) -> None:
    root = tmp_path / "proyecto"
    root.mkdir()
    (root / "cache.db").write_text("x", encoding="utf-8")
    (root / "scanned_folders.json").write_text("{}", encoding="utf-8")
    (root / "historial_escaneo").mkdir()
    (root / "historial_escaneo" / "SCAN_HISTORY.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "Conversión").mkdir()
    (root / "Conversión" / "doc.md").write_text("contenido", encoding="utf-8")
    (root / "project.json").write_text("{}", encoding="utf-8")

    project = _make_project(root)
    await ProjectHistoryCleaner().clear(project)

    assert [p.name for p in root.iterdir()] == ["project.json"]
    payload = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert payload["name"] == "Demo"


@pytest.mark.asyncio
async def test_clear_on_already_empty_project_leaves_only_project_json(tmp_path) -> None:
    root = tmp_path / "proyecto"
    root.mkdir()

    project = _make_project(root)
    await ProjectHistoryCleaner().clear(project)

    assert [p.name for p in root.iterdir()] == ["project.json"]


@pytest.mark.asyncio
async def test_clear_raises_when_root_path_missing(tmp_path) -> None:
    project = _make_project(tmp_path / "no-existe")
    with pytest.raises(ProjectError):
        await ProjectHistoryCleaner().clear(project)
