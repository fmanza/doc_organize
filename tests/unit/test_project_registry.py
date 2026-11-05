"""Tests unitarios de ProjectRegistry (REQ-008)."""

import asyncio
import json
import shutil

from pathlib import Path

import pytest

from doc_organize.core.exceptions import (
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectNameError,
    ProjectNotFoundError,
)
from doc_organize.projects import ProjectRegistry


@pytest.mark.asyncio
async def test_create_project_creates_folder_and_registers(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    registry_path = tmp_path / "projects.json"

    async with ProjectRegistry(registry_path) as registry:
        project = await registry.create_project("Mi Proyecto", base)

    assert project.name == "Mi Proyecto"
    assert (base / "Mi Proyecto").is_dir()
    assert (base / "Mi Proyecto" / "project.json").exists()
    assert registry_path.exists()

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["projects"][0]["name"] == "Mi Proyecto"


@pytest.mark.asyncio
async def test_create_project_rejects_invalid_name(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(ProjectNameError):
            await registry.create_project("CON", base)

    assert list(base.iterdir()) == []


@pytest.mark.asyncio
async def test_create_project_rejects_duplicate_case_insensitive(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Mi Proyecto", base)
        with pytest.raises(ProjectAlreadyExistsError):
            await registry.create_project("mi proyecto", base)

    # Solo se creo una carpeta (la primera); el intento duplicado no toco el disco.
    assert [p.name for p in base.iterdir()] == ["Mi Proyecto"]


@pytest.mark.asyncio
async def test_create_project_rejects_nonexistent_base_location(tmp_path) -> None:
    missing_base = tmp_path / "does-not-exist"

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(ProjectError):
            await registry.create_project("Proyecto", missing_base)


@pytest.mark.asyncio
async def test_create_project_rejects_preexisting_unregistered_folder(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    # Carpeta creada por fuera de la app, con el mismo nombre que se va a pedir.
    (base / "Proyecto Existente").mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(ProjectError):
            await registry.create_project("Proyecto Existente", base)
        projects = await registry.list_projects()

    assert projects == []  # nunca se registro: la carpeta preexistente no era nuestra


@pytest.mark.asyncio
async def test_create_project_rolls_back_folder_on_later_failure(tmp_path, monkeypatch) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async def _boom(self, projects):
        raise RuntimeError("fallo simulado al guardar el registro")

    monkeypatch.setattr(ProjectRegistry, "_save", _boom)

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(RuntimeError):
            await registry.create_project("Proyecto Fallido", base)

    # La carpeta se creo y luego se elimino (rollback), no queda huerfana.
    assert list(base.iterdir()) == []


@pytest.mark.asyncio
async def test_list_projects_returns_all_registered(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto A", base)
        await registry.create_project("Proyecto B", base)
        projects = await registry.list_projects()

    assert {p.name for p in projects} == {"Proyecto A", "Proyecto B"}


@pytest.mark.asyncio
async def test_list_projects_does_not_fail_when_folder_missing(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Movido", base)

    # Simula que el usuario borro/movio la carpeta fuera de la app.
    shutil.rmtree(project.root_path)

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        projects = await registry.list_projects()

    assert len(projects) == 1
    assert projects[0].name == "Proyecto Movido"


@pytest.mark.asyncio
async def test_get_project_case_insensitive(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Mi Proyecto", base)
        found = await registry.get_project("mi PROYECTO")

    assert found.name == "Mi Proyecto"


@pytest.mark.asyncio
async def test_get_project_raises_when_not_found(tmp_path) -> None:
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(ProjectNotFoundError):
            await registry.get_project("No Existe")


@pytest.mark.asyncio
async def test_concurrent_creation_does_not_duplicate_names(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        results = await asyncio.gather(
            registry.create_project("Proyecto Concurrente", base),
            registry.create_project("Proyecto Concurrente", base),
            return_exceptions=True,
        )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ProjectAlreadyExistsError)
    assert [p.name for p in base.iterdir()] == ["Proyecto Concurrente"]


@pytest.mark.asyncio
async def test_corrupt_registry_raises_clear_error(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    registry_path.write_text("{not valid json", encoding="utf-8")

    async with ProjectRegistry(registry_path) as registry:
        with pytest.raises(ProjectError):
            await registry.list_projects()


# ===== Sin tenants desde 1.0.0 (L-12) =====


@pytest.mark.asyncio
async def test_registry_with_legacy_tenant_id_is_still_read(tmp_path: Path) -> None:
    """Un `projects.json` de 0.14.0 con `tenant_id` se sigue leyendo; el campo se ignora y no se vuelve a escribir."""
    base = tmp_path / "workspaces"
    base.mkdir()
    (base / "Antiguo").mkdir()
    registry_path = tmp_path / "projects.json"
    legacy = {"name": "Antiguo", "root_path": str(base / "Antiguo"), "created_at": "2026-01-01T00:00:00+00:00", "tenant_id": "acme"}
    registry_path.write_text(json.dumps({"projects": [legacy]}), encoding="utf-8")

    async with ProjectRegistry(registry_path) as registry:
        assert [p.name for p in await registry.list_projects()] == ["Antiguo"]
        project = await registry.get_project("antiguo")
        await registry.create_project("Nuevo", base)

    assert not hasattr(project, "tenant_id")
    assert "tenant_id" not in registry_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_project_name_is_unique_across_the_whole_registry(tmp_path: Path) -> None:
    first_base = tmp_path / "a"
    second_base = tmp_path / "b"
    first_base.mkdir()
    second_base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Mi Proyecto", first_base)
        with pytest.raises(ProjectAlreadyExistsError):
            await registry.create_project("mi proyecto", second_base)


def test_registry_methods_have_no_tenant_id_parameter() -> None:
    import inspect

    for method in (
        ProjectRegistry.create_project,
        ProjectRegistry.list_projects,
        ProjectRegistry.get_project,
        ProjectRegistry.delete_project,
        ProjectRegistry.move_project_root,
    ):
        assert "tenant_id" not in inspect.signature(method).parameters, method.__name__


# ===== delete_project =====


@pytest.mark.asyncio
async def test_delete_project_removes_folder_and_registry_entry(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Temporal", base)
        (Path(project.root_path) / "algo.txt").write_text("x", encoding="utf-8")

        await registry.delete_project("Temporal")
        projects = await registry.list_projects()

    assert projects == []
    assert not Path(project.root_path).exists()


@pytest.mark.asyncio
async def test_delete_project_raises_when_not_found(tmp_path) -> None:
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(ProjectNotFoundError):
            await registry.delete_project("No Existe")


@pytest.mark.asyncio
async def test_delete_project_keeps_registry_entry_if_folder_removal_fails(tmp_path, monkeypatch) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto", base)

        def _boom(path):
            raise OSError("fallo simulado al borrar la carpeta")

        monkeypatch.setattr(shutil, "rmtree", _boom)

        with pytest.raises(ProjectError):
            await registry.delete_project("Proyecto")

        monkeypatch.undo()
        projects = await registry.list_projects()

    # El proyecto sigue registrado: el borrado fisico fallo, no se desregistro a ciegas.
    assert [p.name for p in projects] == ["Proyecto"]


# ===== move_project_root =====


@pytest.mark.asyncio
async def test_move_project_root_moves_folder_and_updates_registry(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    destination = tmp_path / "otro-destino"
    destination.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Movil", base)
        (Path(project.root_path) / "cache.db").write_text("x", encoding="utf-8")

        moved = await registry.move_project_root("Movil", destination)
        found = await registry.get_project("Movil")

    expected_root = destination / "Movil"
    assert moved.root_path == str(expected_root)
    assert found.root_path == str(expected_root)
    assert (expected_root / "cache.db").exists()
    assert not Path(project.root_path).exists()


@pytest.mark.asyncio
async def test_move_project_root_raises_when_destination_missing(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto", base)
        with pytest.raises(ProjectError):
            await registry.move_project_root("Proyecto", tmp_path / "no-existe")


@pytest.mark.asyncio
async def test_move_project_root_raises_when_destination_already_has_folder(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    destination = tmp_path / "otro-destino"
    destination.mkdir()
    (destination / "Proyecto").mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto", base)
        with pytest.raises(ProjectError):
            await registry.move_project_root("Proyecto", destination)


@pytest.mark.asyncio
async def test_move_project_root_rolls_back_move_on_registry_save_failure(tmp_path, monkeypatch) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    destination = tmp_path / "otro-destino"
    destination.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto", base)
        original_root = Path(project.root_path)

        async def _boom(self, projects):
            raise RuntimeError("fallo simulado al guardar el registro")

        monkeypatch.setattr(ProjectRegistry, "_save", _boom)

        with pytest.raises(RuntimeError):
            await registry.move_project_root("Proyecto", destination)

    # La carpeta fisica volvio a su sitio original: el registro nunca se actualizo.
    assert original_root.is_dir()
    assert not (destination / "Proyecto").exists()


@pytest.mark.asyncio
async def test_move_project_root_raises_when_not_found(tmp_path) -> None:
    destination = tmp_path / "otro-destino"
    destination.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        with pytest.raises(ProjectNotFoundError):
            await registry.move_project_root("No Existe", destination)
