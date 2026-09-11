"""Tests de control de acceso a proyectos por rol (revisión 9).

Un rol restringido (`is_admin=False`) solo debe ver/operar los proyectos listados
en su `project_names`; cualquier otro proyecto del mismo tenant debe comportarse
como si no existiera (404 uniforme, no 403 — mismo criterio de no-enumeración que
`ProjectRegistry.get_project()`).
"""

import httpx
import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig
from doc_organize.web import create_app

_TENANT_NAME = "Acme Corp"
_TENANT_ID = "acme-corp"
_ADMIN_USERNAME = "admin"
_ADMIN_PASSWORD = "admin-s3cret-pw"


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


def _non_loopback_app(tmp_path):
    security = SecurityConfig(bind_host="0.0.0.0")
    return create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")


async def _setup(tmp_path):
    """Crea el tenant (con un usuario admin propio -- `create_tenant()` ya no
    aprovisiona ninguno, rediseño Tenant/Role/User), un proyecto 'Proyecto A' y
    'Proyecto B' (admin), y un usuario 'reader' restringido con acceso solo a
    'Proyecto A'. Devuelve la app."""
    base = tmp_path / "workspaces"
    base.mkdir()
    app = _non_loopback_app(tmp_path)

    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant(_TENANT_NAME)
        admin_role = next((role for role in await store.list_roles() if role.is_admin), None)
        if admin_role is None:
            admin_role = await store.create_role("admin", is_admin=True)
        await store.create_user(tenant.id, _ADMIN_USERNAME, _ADMIN_PASSWORD, role_id=admin_role.id)

    async with _client(app) as admin_client:
        await admin_client.post("/login", data={"tenant_id": _TENANT_ID, "username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD})
        await admin_client.post("/api/projects", json={"name": "Proyecto A", "base_location": str(base)})
        await admin_client.post("/api/projects", json={"name": "Proyecto B", "base_location": str(base)})

    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Lector", project_names=["Proyecto A"])
        await store.create_user(_TENANT_ID, "reader", "s3cr3t-password", role_id=role.id)

    return app


async def _login_reader(client: httpx.AsyncClient) -> None:
    await client.post("/login", data={"tenant_id": _TENANT_ID, "username": "reader", "password": "s3cr3t-password"})


@pytest.mark.asyncio
async def test_list_projects_filtered_to_allowed_only(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/api/projects")

    names = [p["name"] for p in response.json()["projects"]]
    assert names == ["Proyecto A"]


@pytest.mark.asyncio
async def test_get_allowed_project_succeeds(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/api/projects/Proyecto%20A")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_disallowed_project_returns_404(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/api/projects/Proyecto%20B")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scan_page_disallowed_project_returns_404(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/projects/Proyecto%20B/scan")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cache_viewer_disallowed_project_returns_404(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/projects/Proyecto%20B/cache")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_duplicates_disallowed_project_returns_404(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/api/projects/Proyecto%20B/duplicates")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_zip_disallowed_project_returns_404(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/downloads/projects/Proyecto%20B/export.zip")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reader_cannot_create_project(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.post("/api/projects", json={"name": "Proyecto C", "base_location": str(tmp_path)})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_page_disallowed_project_returns_404(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/projects/Proyecto%20B")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_project_selector_page_filtered_to_allowed_only(tmp_path) -> None:
    app = await _setup(tmp_path)
    async with _client(app) as client:
        await _login_reader(client)
        response = await client.get("/")
    assert "Proyecto A" in response.text
    assert "Proyecto B" not in response.text
