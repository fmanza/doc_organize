"""Tests unitarios de ScannedFoldersStore (menú Escaneo: lista persistente de carpetas)."""

import json

import pytest

from doc_organize.core.exceptions import InvalidPathError, ScannedFolderInUseError, ScannedFolderNotFoundError
from doc_organize.core.models import Project
from doc_organize.projects import ScannedFoldersStore


def _project(tmp_path) -> Project:
    root = tmp_path / "Proyecto"
    root.mkdir()
    return Project(name="Proyecto", root_path=str(root), created_at="2026-08-30T00:00:00+00:00")


@pytest.mark.asyncio
async def test_add_folder_persists_entry(tmp_path) -> None:
    project = _project(tmp_path)
    folder = tmp_path / "datos"
    folder.mkdir()
    store = ScannedFoldersStore()

    entry = await store.add_folder(project, str(folder))

    assert entry.path == str(folder.resolve())
    assert entry.used is False

    registry_path = tmp_path / "Proyecto" / "scanned_folders.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["folders"][0]["path"] == str(folder.resolve())


@pytest.mark.asyncio
async def test_add_folder_rejects_nonexistent_path(tmp_path) -> None:
    project = _project(tmp_path)
    store = ScannedFoldersStore()

    with pytest.raises(InvalidPathError):
        await store.add_folder(project, str(tmp_path / "no-existe"))


@pytest.mark.asyncio
async def test_add_folder_is_idempotent(tmp_path) -> None:
    project = _project(tmp_path)
    folder = tmp_path / "datos"
    folder.mkdir()
    store = ScannedFoldersStore()

    first = await store.add_folder(project, str(folder))
    second = await store.add_folder(project, str(folder))

    assert first == second
    folders = await store.list_folders(project)
    assert len(folders) == 1


@pytest.mark.asyncio
async def test_remove_folder_deletes_unused_entry(tmp_path) -> None:
    project = _project(tmp_path)
    folder = tmp_path / "datos"
    folder.mkdir()
    store = ScannedFoldersStore()
    await store.add_folder(project, str(folder))

    await store.remove_folder(project, str(folder))

    assert await store.list_folders(project) == []


@pytest.mark.asyncio
async def test_remove_folder_rejects_unknown_path(tmp_path) -> None:
    project = _project(tmp_path)
    store = ScannedFoldersStore()

    with pytest.raises(ScannedFolderNotFoundError):
        await store.remove_folder(project, str(tmp_path))


@pytest.mark.asyncio
async def test_remove_folder_rejects_used_entry(tmp_path) -> None:
    project = _project(tmp_path)
    folder = tmp_path / "datos"
    folder.mkdir()
    store = ScannedFoldersStore()
    await store.add_folder(project, str(folder))
    await store.mark_used(project, [str(folder)])

    with pytest.raises(ScannedFolderInUseError):
        await store.remove_folder(project, str(folder))


@pytest.mark.asyncio
async def test_mark_used_flags_existing_entry(tmp_path) -> None:
    project = _project(tmp_path)
    folder = tmp_path / "datos"
    folder.mkdir()
    store = ScannedFoldersStore()
    await store.add_folder(project, str(folder))

    await store.mark_used(project, [str(folder)])

    [entry] = await store.list_folders(project)
    assert entry.used is True


@pytest.mark.asyncio
async def test_mark_used_creates_entry_for_untracked_path(tmp_path) -> None:
    """Una ruta escaneada por otra vía (CLI, API directa) que nunca pasó por
    `add_folder` debe quedar registrada igualmente, como historial completo de
    lo escaneado."""
    project = _project(tmp_path)
    folder = tmp_path / "datos"
    folder.mkdir()
    store = ScannedFoldersStore()

    await store.mark_used(project, [str(folder)])

    [entry] = await store.list_folders(project)
    assert entry.path == str(folder.resolve())
    assert entry.used is True


@pytest.mark.asyncio
async def test_list_folders_orders_most_recent_first(tmp_path) -> None:
    project = _project(tmp_path)
    older = tmp_path / "older"
    older.mkdir()
    newer = tmp_path / "newer"
    newer.mkdir()
    store = ScannedFoldersStore()

    await store.add_folder(project, str(older))
    await store.add_folder(project, str(newer))

    folders = await store.list_folders(project)
    assert [f.path for f in folders] == [str(newer.resolve()), str(older.resolve())]
