"""Tests de las rutas de gestión de proyectos: impacto, vaciar histórico, eliminar
y mover (REQ-008 vía HTTP). Todas admin-only y requieren `confirm: true` en el payload."""

import httpx
import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.constants import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME
from doc_organize.core.models import SecurityConfig
from doc_organize.web import create_app

_TENANT_NAME = "Acme Corp"
_TENANT_ID = "acme-corp"


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


def _non_loopback_app(tmp_path):
    security = SecurityConfig(bind_host="0.0.0.0")
    return create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")


async def _setup(tmp_path):
    """Crea el tenant, 'Proyecto A' (con contenido dentro), y un usuario 'reader'
    restringido con acceso a 'Proyecto A' pero sin rol admin. Devuelve (app, base)."""
    base = tmp_path / "workspaces"
    base.mkdir()
    app = _non_loopback_app(tmp_path)

    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_tenant(_TENANT_NAME)

    async with _client(app) as admin_client:
        await admin_client.post("/login", data={"tenant_id": _TENANT_ID, "username": DEFAULT_ADMIN_USERNAME, "password": DEFAULT_ADMIN_PASSWORD})
        await admin_client.post(
            "/change-password",
            data={"current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "nueva-admin-pw", "confirm_password": "nueva-admin-pw"},
        )
        await admin_client.post("/api/projects", json={"name": "Proyecto A", "base_location": str(base)})

    root = base / "Proyecto A"
    (root / "cache.db").write_text("x", encoding="utf-8")

    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role(_TENANT_ID, "Lector", project_names=["Proyecto A"])
        await store.create_user(_TENANT_ID, "reader", "s3cr3t-password", role_id=role.id)

    return app, base


async def _login_admin(client: httpx.AsyncClient) -> None:
    await client.post("/login", data={"tenant_id": _TENANT_ID, "username": DEFAULT_ADMIN_USERNAME, "password": "nueva-admin-pw"})


async def _login_reader(client: httpx.AsyncClient) -> None:
    await client.post("/login", data={"tenant_id": _TENANT_ID, "username": "reader", "password": "s3cr3t-password"})


# ===== impact =====


@pytest.mark.asyncio
async def test_get_impact_as_admin_counts_files(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.get("/api/projects/Proyecto A/impact")

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_count"] >= 1
    assert payload["has_active_operation"] is False


@pytest.mark.asyncio
async def test_get_impact_as_non_admin_forbidden(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/api/projects/Proyecto A/impact")

    assert response.status_code == 403


# ===== clear-history =====


@pytest.mark.asyncio
async def test_clear_history_requires_confirm_flag(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.post("/api/projects/Proyecto A/clear-history", json={"confirm": False})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_clear_history_wipes_project_contents(tmp_path) -> None:
    app, base = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.post("/api/projects/Proyecto A/clear-history", json={"confirm": True})

    assert response.status_code == 204
    root = base / "Proyecto A"
    assert [p.name for p in root.iterdir()] == ["project.json"]


@pytest.mark.asyncio
async def test_clear_history_as_non_admin_forbidden(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.post("/api/projects/Proyecto A/clear-history", json={"confirm": True})

    assert response.status_code == 403


# ===== delete =====


@pytest.mark.asyncio
async def test_delete_project_requires_confirm_flag(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.request("DELETE", "/api/projects/Proyecto A", json={"confirm": False})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_delete_project_removes_folder_and_listing(tmp_path) -> None:
    app, base = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.request("DELETE", "/api/projects/Proyecto A", json={"confirm": True})
        listing = await client.get("/api/projects")

    assert response.status_code == 204
    assert not (base / "Proyecto A").exists()
    assert listing.json()["projects"] == []


@pytest.mark.asyncio
async def test_delete_project_as_non_admin_forbidden(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.request("DELETE", "/api/projects/Proyecto A", json={"confirm": True})

    assert response.status_code == 403


# ===== move =====


@pytest.mark.asyncio
async def test_move_project_requires_confirm_flag(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    destination = tmp_path / "otro-destino"
    destination.mkdir()
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.post("/api/projects/Proyecto A/move", json={"destination_path": str(destination), "confirm": False})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_move_project_moves_folder_and_updates_root_path(tmp_path) -> None:
    app, base = await _setup(tmp_path)
    destination = tmp_path / "otro-destino"
    destination.mkdir()
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.post("/api/projects/Proyecto A/move", json={"destination_path": str(destination), "confirm": True})

    assert response.status_code == 200
    expected_root = destination / "Proyecto A"
    assert response.json()["root_path"] == str(expected_root)
    assert (expected_root / "cache.db").exists()
    assert not (base / "Proyecto A").exists()


@pytest.mark.asyncio
async def test_move_project_as_non_admin_forbidden(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    destination = tmp_path / "otro-destino"
    destination.mkdir()
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.post("/api/projects/Proyecto A/move", json={"destination_path": str(destination), "confirm": True})

    assert response.status_code == 403


# ===== bloqueo con operacion en curso =====


@pytest.mark.asyncio
async def test_clear_history_rejected_while_operation_in_progress(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    app.state.active_project_operations.add((_TENANT_ID, "proyecto a"))
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.post("/api/projects/Proyecto A/clear-history", json={"confirm": True})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_delete_project_rejected_while_operation_in_progress(tmp_path) -> None:
    app, _ = await _setup(tmp_path)
    app.state.active_project_operations.add((_TENANT_ID, "proyecto a"))
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.request("DELETE", "/api/projects/Proyecto A", json={"confirm": True})

    assert response.status_code == 409
