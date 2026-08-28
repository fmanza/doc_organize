"""Tests unitarios de ProjectRegistry (REQ-008)."""

import asyncio
import json
import shutil

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


# ===== Tenant-scoping (revision 8, SS2.7.2) =====


@pytest.mark.asyncio
async def test_create_project_defaults_to_default_tenant(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Mi Proyecto", base)

    assert project.tenant_id == "default"


@pytest.mark.asyncio
async def test_same_project_name_allowed_in_different_tenants(tmp_path) -> None:
    # Cada tenant usa su propia base_location -- el caso realista (organizaciones
    # distintas normalmente no comparten carpeta padre). Si dos tenants usaran la
    # MISMA base_location con el MISMO nombre, la colision seria a nivel de
    # sistema de archivos (root_path identico), no de registro: sigue siendo un
    # ProjectError, igual que ya ocurre con cualquier carpeta preexistente no
    # registrada (test_create_project_rejects_preexisting_unregistered_folder).
    acme_base = tmp_path / "acme-workspaces"
    acme_base.mkdir()
    globex_base = tmp_path / "globex-workspaces"
    globex_base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        acme_project = await registry.create_project("Mi Proyecto", acme_base, tenant_id="acme-corp")
        globex_project = await registry.create_project("Mi Proyecto", globex_base, tenant_id="globex-inc")

    assert acme_project.root_path != globex_project.root_path
    assert acme_project.tenant_id == "acme-corp"
    assert globex_project.tenant_id == "globex-inc"


@pytest.mark.asyncio
async def test_same_project_name_rejected_within_same_tenant(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Mi Proyecto", base, tenant_id="acme-corp")
        with pytest.raises(ProjectAlreadyExistsError):
            await registry.create_project("mi proyecto", base, tenant_id="acme-corp")


@pytest.mark.asyncio
async def test_list_projects_only_returns_own_tenant(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto Acme", base, tenant_id="acme-corp")
        await registry.create_project("Proyecto Globex", base, tenant_id="globex-inc")

        acme_projects = await registry.list_projects(tenant_id="acme-corp")
        globex_projects = await registry.list_projects(tenant_id="globex-inc")

    assert [p.name for p in acme_projects] == ["Proyecto Acme"]
    assert [p.name for p in globex_projects] == ["Proyecto Globex"]


@pytest.mark.asyncio
async def test_get_project_from_other_tenant_raises_not_found(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto Acme", base, tenant_id="acme-corp")
        with pytest.raises(ProjectNotFoundError):
            await registry.get_project("Proyecto Acme", tenant_id="globex-inc")
