"""Tests de gestión de roles y usuarios vía HTTP (revisión 9)."""

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


async def _create_tenant(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_tenant(_TENANT_NAME)


async def _create_restricted_user(tmp_path, username: str, password: str, project_names=None) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role(_TENANT_ID, f"role-{username}", project_names=project_names or [])
        await store.create_user(_TENANT_ID, username, password, role_id=role.id)


async def _login_admin(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post(
        "/login", data={"tenant_id": _TENANT_ID, "username": DEFAULT_ADMIN_USERNAME, "password": DEFAULT_ADMIN_PASSWORD}
    )


@pytest.mark.asyncio
async def test_default_admin_user_can_login_and_is_forced_to_change_password(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        blocked = await client.get("/api/projects")
        redirected_page = await client.get("/", follow_redirects=False)

    assert blocked.status_code == 403
    assert redirected_page.status_code == 303
    assert redirected_page.headers["location"] == "/change-password"


@pytest.mark.asyncio
async def test_non_admin_user_gets_403_on_admin_routes(tmp_path) -> None:
    await _create_tenant(tmp_path)
    await _create_restricted_user(tmp_path, "alice", "s3cr3t-password")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await client.post("/login", data={"tenant_id": _TENANT_ID, "username": "alice", "password": "s3cr3t-password"})
        list_roles = await client.get("/api/roles")
        list_users = await client.get("/api/users")
        create_role = await client.post("/api/roles", json={"name": "Nuevo", "is_admin": False, "project_names": []})

    assert list_roles.status_code == 403
    assert list_users.status_code == 403
    assert create_role.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_role_and_user_via_api(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        await client.post("/change-password", data={
            "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "nueva-admin-pw", "confirm_password": "nueva-admin-pw",
        })

        create_role = await client.post(
            "/api/roles", json={"name": "Lector", "is_admin": False, "project_names": ["Proyecto A"]}
        )
        assert create_role.status_code == 201
        role_id = create_role.json()["id"]

        create_user = await client.post(
            "/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role_id}
        )
        assert create_user.status_code == 201
        assert create_user.json()["role_id"] == role_id
        assert create_user.json()["must_change_password"] is False

        list_users = await client.get("/api/users")

    usernames = {user["username"] for user in list_users.json()["users"]}
    assert {"admin", "carol"} == usernames


@pytest.mark.asyncio
async def test_create_role_with_allowed_scan_roots(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin_and_change_password(client)
        create_role = await client.post(
            "/api/roles",
            json={"name": "Lector", "is_admin": False, "project_names": ["Proyecto A"], "allowed_scan_roots": ["/repo/entrada"]},
        )
    assert create_role.status_code == 201
    assert create_role.json()["allowed_scan_roots"] == ["/repo/entrada"]


@pytest.mark.asyncio
async def test_create_role_admin_with_scan_roots_returns_422(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin_and_change_password(client)
        response = await client.post(
            "/api/roles", json={"name": "Super", "is_admin": True, "allowed_scan_roots": ["/repo/entrada"]}
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_role_admin_with_projects_returns_422(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        await client.post("/change-password", data={
            "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "nueva-admin-pw", "confirm_password": "nueva-admin-pw",
        })
        response = await client.post(
            "/api/roles", json={"name": "Super", "is_admin": True, "project_names": ["Proyecto A"]}
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_last_admin_role_returns_409(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        await client.post("/change-password", data={
            "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "nueva-admin-pw", "confirm_password": "nueva-admin-pw",
        })
        roles = (await client.get("/api/roles")).json()["roles"]
        admin_role_id = next(r["id"] for r in roles if r["is_admin"])
        response = await client.delete(f"/api/roles/{admin_role_id}")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_admin_users_page_loads_for_admin(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        await client.post("/change-password", data={
            "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "nueva-admin-pw", "confirm_password": "nueva-admin-pw",
        })
        response = await client.get("/admin/users")
    assert response.status_code == 200
    assert "admin" in response.text


async def _login_admin_and_change_password(client: httpx.AsyncClient) -> None:
    await _login_admin(client)
    await client.post("/change-password", data={
        "current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "nueva-admin-pw", "confirm_password": "nueva-admin-pw",
    })


@pytest.mark.asyncio
async def test_get_update_and_delete_role_via_api(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin_and_change_password(client)

        created = await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})
        role_id = created.json()["id"]

        fetched = await client.get(f"/api/roles/{role_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Lector"

        updated = await client.patch(f"/api/roles/{role_id}", json={"project_names": ["Proyecto X"]})
        assert updated.status_code == 200
        assert updated.json()["project_names"] == ["Proyecto X"]

        deleted = await client.delete(f"/api/roles/{role_id}")
        assert deleted.status_code == 204

        gone = await client.get(f"/api/roles/{role_id}")
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_get_update_and_delete_user_via_api(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin_and_change_password(client)

        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()
        created = await client.post("/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role["id"]})
        user_id = created.json()["id"]

        fetched = await client.get(f"/api/users/{user_id}")
        assert fetched.status_code == 200
        assert fetched.json()["username"] == "carol"

        reset = await client.patch(f"/api/users/{user_id}", json={"password": "otra-password"})
        assert reset.status_code == 200
        assert reset.json()["must_change_password"] is True

        deleted = await client.delete(f"/api/users/{user_id}")
        assert deleted.status_code == 204

        gone = await client.get(f"/api/users/{user_id}")
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_delete_role_in_use_returns_409(tmp_path) -> None:
    await _create_tenant(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin_and_change_password(client)
        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()
        await client.post("/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role["id"]})

        response = await client.delete(f"/api/roles/{role['id']}")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_loopback_mode_has_no_admin_restrictions(tmp_path) -> None:
    """En loopback/sin auth no hay sesión ni rol que resolver: sin restricciones,
    mismo comportamiento que el resto de la app en ese modo (revisión 8)."""
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")
    async with _client(app) as client:
        response = await client.get("/api/roles")
    assert response.status_code == 200
    assert response.json() == {"roles": []}
