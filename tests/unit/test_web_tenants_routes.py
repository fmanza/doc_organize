"""Tests de la pantalla cruzada "Tenants y usuarios" (`web/routes/tenants.py`,
rediseño Tenant/Role/User, decisión de diseño 3): solo `is_instance_admin`."""

import httpx
import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.constants import DEFAULT_ADMIN_PASSWORD, DEFAULT_TENANT_ID
from doc_organize.core.models import SecurityConfig
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app

_INSTANCE_ADMIN_PASSWORD = "instance-admin-pw"


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


def _non_loopback_app(tmp_path):
    security = SecurityConfig(bind_host="0.0.0.0")
    return create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")


async def _prepare_instance_admin(tmp_path) -> None:
    """Fija una contraseña conocida (y limpia `must_change_password`) para el
    usuario admin de fábrica del tenant por defecto, ya `is_instance_admin=True`
    desde el bootstrap -- evita chocar con el bloqueo de login de la decisión 1
    (exclusivo de la contraseña de FÁBRICA sin cambiar)."""
    async with AuthStore(tmp_path / "auth.db") as store:
        default_admin = (await store.list_users(DEFAULT_TENANT_ID))[0]
        await store.change_password(default_admin.id, DEFAULT_ADMIN_PASSWORD, _INSTANCE_ADMIN_PASSWORD)


async def _login_instance_admin(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/login", data={"tenant_id": DEFAULT_TENANT_ID, "username": "admin", "password": _INSTANCE_ADMIN_PASSWORD})


async def _create_tenant_admin(tmp_path, tenant_name: str, username: str, password: str) -> str:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant(tenant_name)
        admin_role = next((role for role in await store.list_roles() if role.is_admin), None)
        if admin_role is None:
            admin_role = await store.create_role("admin", is_admin=True)
        await store.create_user(tenant.id, username, password, role_id=admin_role.id)
    return tenant.id


@pytest.mark.asyncio
async def test_plain_tenant_admin_gets_403_on_tenants_routes(tmp_path) -> None:
    await _create_tenant_admin(tmp_path, "Acme Corp", "admin", "s3cr3t-password")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await client.post("/login", data={"tenant_id": "acme-corp", "username": "admin", "password": "s3cr3t-password"})
        response = await client.get("/api/tenants")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_instance_admin_can_list_and_create_tenants(tmp_path) -> None:
    await _prepare_instance_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)

        created = await client.post("/api/tenants", json={"name": "Acme Corp"})
        assert created.status_code == 201
        assert created.json()["id"] == "acme-corp"

        listed = await client.get("/api/tenants")
    tenant_ids = {t["id"] for t in listed.json()["tenants"]}
    assert tenant_ids == {DEFAULT_TENANT_ID, "acme-corp"}


@pytest.mark.asyncio
async def test_instance_admin_can_create_user_in_any_tenant(tmp_path) -> None:
    """Necesario porque `create_tenant()` ya no aprovisiona ningún usuario (rediseño
    Tenant/Role/User) -- esta es la vía normal para dar de alta el primer usuario
    de un tenant nuevo desde la UI, sin volver a la CLI."""
    await _prepare_instance_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)
        await client.post("/api/tenants", json={"name": "Acme Corp"})
        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()

        created = await client.post("/api/tenants/acme-corp/users", json={"username": "alice", "password": "s3cr3t-password", "role_id": role["id"]})
    assert created.status_code == 201
    assert created.json()["tenant_id"] == "acme-corp"


@pytest.mark.asyncio
async def test_instance_admin_can_grant_and_revoke_is_instance_admin_on_other_tenant_user(tmp_path) -> None:
    await _prepare_instance_admin(tmp_path)
    tenant_id = await _create_tenant_admin(tmp_path, "Acme Corp", "bob", "s3cr3t-password")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)
        async with AuthStore(tmp_path / "auth.db") as store:
            bob = next(u for u in await store.list_users(tenant_id) if u.username == "bob")

        granted = await client.patch(f"/api/tenants/{tenant_id}/users/{bob.id}", json={"is_instance_admin": True})
        assert granted.status_code == 200
        assert granted.json()["is_instance_admin"] is True

        revoked = await client.patch(f"/api/tenants/{tenant_id}/users/{bob.id}", json={"is_instance_admin": False})
        assert revoked.json()["is_instance_admin"] is False


@pytest.mark.asyncio
async def test_plain_tenant_admin_update_user_cannot_grant_instance_admin(tmp_path) -> None:
    """`/api/users/{id}` (router de admin.py, propio tenant) ignora
    `is_instance_admin` en el payload -- solo `/api/tenants/{tid}/users/{id}`
    (este router) puede tocarlo, y exige `is_instance_admin` en quien llama."""
    tenant_id = await _create_tenant_admin(tmp_path, "Acme Corp", "admin", "s3cr3t-password")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await client.post("/login", data={"tenant_id": tenant_id, "username": "admin", "password": "s3cr3t-password"})
        async with AuthStore(tmp_path / "auth.db") as store:
            admin_user = (await store.list_users(tenant_id))[0]
        response = await client.patch(f"/api/tenants/{tenant_id}/users/{admin_user.id}", json={"is_instance_admin": True})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_tenant_with_projects_returns_409(tmp_path) -> None:
    await _prepare_instance_admin(tmp_path)
    tenant_id = await _create_tenant_admin(tmp_path, "Acme Corp", "bob", "s3cr3t-password")
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        await registry.create_project("Proyecto A", base, tenant_id=tenant_id)

    async with AuthStore(tmp_path / "auth.db") as store:
        bob = (await store.list_users(tenant_id))[0]
        await store.delete_user(tenant_id, bob.id)

    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)
        response = await client.delete(f"/api/tenants/{tenant_id}")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_delete_empty_tenant_succeeds(tmp_path) -> None:
    await _prepare_instance_admin(tmp_path)
    tenant_id = await _create_tenant_admin(tmp_path, "Acme Corp", "bob", "s3cr3t-password")
    async with AuthStore(tmp_path / "auth.db") as store:
        bob = (await store.list_users(tenant_id))[0]
        await store.delete_user(tenant_id, bob.id)

    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)
        response = await client.delete(f"/api/tenants/{tenant_id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_admin_tenants_page_loads_for_instance_admin(tmp_path) -> None:
    await _prepare_instance_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)
        response = await client.get("/admin/tenants")
    assert response.status_code == 200
    assert DEFAULT_TENANT_ID in response.text


@pytest.mark.asyncio
async def test_admin_tenants_page_shows_role_name_not_raw_id(tmp_path) -> None:
    """La tabla de usuarios de cada tenant muestra el NOMBRE del rol (`roles_by_id`),
    no su UUID crudo -- el `<select>` del formulario de alta sigue usando el id
    como `value` de cada `<option>` (necesario para el payload), eso es aparte."""
    await _prepare_instance_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_instance_admin(client)
        response = await client.get("/admin/tenants")

    async with AuthStore(tmp_path / "auth.db") as store:
        admin_role = next(role for role in await store.list_roles() if role.is_admin)

    # Fragmento exacto de la celda de la tabla (no del <option> del formulario de
    # alta, que también contiene el nombre del rol como texto).
    assert f'<td class="px-2.5 py-1.5 border-b border-gray-300">{admin_role.name}</td>' in response.text


@pytest.mark.asyncio
async def test_loopback_mode_has_no_instance_admin_restrictions(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")
    async with _client(app) as client:
        response = await client.get("/api/tenants")
    assert response.status_code == 200
    tenant_ids = {t["id"] for t in response.json()["tenants"]}
    assert tenant_ids == {DEFAULT_TENANT_ID}
