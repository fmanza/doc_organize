"""Tests de gestión de roles y usuarios vía HTTP (revisión 9; rediseño Tenant/Role/User:
Role global sin tenant_id/allowed_scan_roots, User con is_blocked/is_instance_admin)."""

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


async def _create_tenant_with_admin(tmp_path) -> None:
    """Tenant + un usuario admin propio, con contraseña ya elegida (`must_change_password=False`).

    `AuthStore.create_tenant()` ya no aprovisiona ningún usuario (rediseño
    Tenant/Role/User) — este helper reemplaza el bootstrap antiguo para que las
    pruebas de este fichero (CRUD admin vía API, no el bootstrap en sí) no
    dependan de la cuenta de fábrica, que además ya no puede completar el login
    en modo no-loopback (`test_web_auth.py` cubre esa cuenta específicamente).
    """
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant(_TENANT_NAME)
        admin_role = next((role for role in await store.list_roles() if role.is_admin), None)
        if admin_role is None:
            admin_role = await store.create_role("admin", is_admin=True)
        await store.create_user(tenant.id, _ADMIN_USERNAME, _ADMIN_PASSWORD, role_id=admin_role.id)


async def _create_restricted_user(tmp_path, username: str, password: str, project_names=None) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role(f"role-{username}", project_names=project_names or [])
        await store.create_user(_TENANT_ID, username, password, role_id=role.id)


async def _login_admin(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/login", data={"tenant_id": _TENANT_ID, "username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD})


@pytest.mark.asyncio
async def test_non_admin_user_gets_403_on_admin_routes(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
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
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)

        create_role = await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": ["Proyecto A"]})
        assert create_role.status_code == 201
        role_id = create_role.json()["id"]

        create_user = await client.post("/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role_id})
        assert create_user.status_code == 201
        assert create_user.json()["role_id"] == role_id
        assert create_user.json()["must_change_password"] is False
        assert create_user.json()["is_blocked"] is False
        assert create_user.json()["is_instance_admin"] is False

        list_users = await client.get("/api/users")

    usernames = {user["username"] for user in list_users.json()["users"]}
    assert {_ADMIN_USERNAME, "carol"} == usernames


@pytest.mark.asyncio
async def test_role_response_has_no_allowed_scan_roots_field(tmp_path) -> None:
    """Rediseño Tenant/Role/User: `allowed_scan_roots` se retira por completo del
    contrato de `/api/roles` -- el acceso de escaneo pasa a ser implícito por
    proyecto (ver `test_web_filesystem.py`/`test_web_scan.py`)."""
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        created = await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": ["Proyecto A"]})
    assert created.status_code == 201
    assert "allowed_scan_roots" not in created.json()


@pytest.mark.asyncio
async def test_create_role_admin_with_projects_returns_422(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.post("/api/roles", json={"name": "Super", "is_admin": True, "project_names": ["Proyecto A"]})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_last_admin_role_in_the_system_returns_409(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        roles = (await client.get("/api/roles")).json()["roles"]
        admin_role_id = next(r["id"] for r in roles if r["is_admin"])
        response = await client.delete(f"/api/roles/{admin_role_id}")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_admin_users_page_loads_for_admin(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.get("/admin/users")
    assert response.status_code == 200
    assert _ADMIN_USERNAME in response.text
    assert "Crear rol" not in response.text


@pytest.mark.asyncio
async def test_admin_roles_page_loads_for_admin_with_projects(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        await client.post("/api/projects", json={"name": "Proyecto A", "base_location": str(tmp_path)})
        response = await client.get("/admin/roles")
    assert response.status_code == 200
    assert "Crear rol" in response.text
    assert "Proyecto A" in response.text
    assert "Crear usuario" not in response.text
    assert "Raíces de escaneo" not in response.text  # retirado (acceso implícito por proyecto)


_PROYECTOS_ADMIN_LINK = '<a class="block text-blue-600 underline" href="/">Proyectos</a>'


@pytest.mark.asyncio
async def test_admin_sidebar_shows_proyectos_shortcut(tmp_path) -> None:
    """El bloque Admin del sidebar enlaza a la gestión de proyectos (`/`), antes
    solo alcanzable vía el logo -- ver docs/functional/admin.md."""
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.get("/admin/roles")
    assert response.status_code == 200
    assert _PROYECTOS_ADMIN_LINK in response.text


@pytest.mark.asyncio
async def test_non_admin_sidebar_does_not_show_proyectos_shortcut(tmp_path) -> None:
    """Sin `is_admin`/`is_instance_admin` no se ve el bloque Admin -- por tanto
    tampoco el atajo "Proyectos" -- aunque siga llegando a `/` por el logo."""
    await _create_tenant_with_admin(tmp_path)
    await _create_restricted_user(tmp_path, "alice", "s3cr3t-password")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await client.post("/login", data={"tenant_id": _TENANT_ID, "username": "alice", "password": "s3cr3t-password"})
        response = await client.get("/")
    assert response.status_code == 200
    assert _PROYECTOS_ADMIN_LINK not in response.text


@pytest.mark.asyncio
async def test_admin_roles_page_shows_assigned_usernames_filtered_to_own_tenant(tmp_path) -> None:
    """Un rol es global y puede estar en uso en otro tenant a la vez -- `/admin/roles`
    solo debe listar, por rol, los usernames del PROPIO tenant de quien consulta
    (AUDIT_PLAN, condición de no-enumeración cross-tenant)."""
    async with AuthStore(tmp_path / "auth.db") as store:
        acme = await store.create_tenant(_TENANT_NAME)
        globex = await store.create_tenant("Globex Inc")
        shared_role = await store.create_role("Lector", project_names=[])
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        await store.create_user(acme.id, _ADMIN_USERNAME, _ADMIN_PASSWORD, role_id=admin_role.id)
        await store.create_user(acme.id, "alice-acme", "s3cr3t-password", role_id=shared_role.id)
        await store.create_user(globex.id, "bob-globex", "s3cr3t-password", role_id=shared_role.id)

    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        response = await client.get("/admin/roles")

    assert response.status_code == 200
    assert "alice-acme" in response.text
    assert "bob-globex" not in response.text


@pytest.mark.asyncio
async def test_create_user_with_must_change_password_checkbox(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()

        forced = await client.post(
            "/api/users",
            json={"username": "dave", "password": "s3cr3t-password", "role_id": role["id"], "must_change_password": True},
        )
        assert forced.status_code == 201
        assert forced.json()["must_change_password"] is True

        not_forced = await client.post(
            "/api/users",
            json={"username": "erin", "password": "s3cr3t-password", "role_id": role["id"]},
        )
        assert not_forced.status_code == 201
        assert not_forced.json()["must_change_password"] is False


@pytest.mark.asyncio
async def test_get_update_and_delete_role_via_api(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)

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
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)

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
async def test_update_user_can_block_and_unblock_via_api(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()
        created = await client.post("/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role["id"]})
        user_id = created.json()["id"]

        blocked = await client.patch(f"/api/users/{user_id}", json={"is_blocked": True})
        assert blocked.status_code == 200
        assert blocked.json()["is_blocked"] is True

        unblocked = await client.patch(f"/api/users/{user_id}", json={"is_blocked": False})
        assert unblocked.json()["is_blocked"] is False


@pytest.mark.asyncio
async def test_update_user_cannot_set_is_instance_admin_via_this_router(tmp_path) -> None:
    """Solo `PATCH /api/tenants/{tenant_id}/users/{user_id}` (instance-admin) puede
    tocar `is_instance_admin` -- `/api/users/{id}` (este router) ni siquiera acepta
    ese campo en el payload (decisión de diseño 3)."""
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()
        created = await client.post("/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role["id"]})
        user_id = created.json()["id"]

        response = await client.patch(f"/api/users/{user_id}", json={"is_instance_admin": True})

    assert response.status_code == 200
    assert response.json()["is_instance_admin"] is False  # el campo desconocido se ignora, no escala privilegios


@pytest.mark.asyncio
async def test_delete_role_in_use_returns_409(tmp_path) -> None:
    await _create_tenant_with_admin(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login_admin(client)
        role = (await client.post("/api/roles", json={"name": "Lector", "is_admin": False, "project_names": []})).json()
        await client.post("/api/users", json={"username": "carol", "password": "s3cr3t-password", "role_id": role["id"]})

        response = await client.delete(f"/api/roles/{role['id']}")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_loopback_mode_has_no_admin_restrictions(tmp_path) -> None:
    """En loopback/sin auth no hay sesión ni rol que resolver: sin restricciones,
    mismo comportamiento que el resto de la app en ese modo (revisión 8).

    El único rol que existe en una base recién creada es el de fábrica del tenant
    por defecto (rediseño Tenant/Role/User: `AuthStore` lo aprovisiona en cada
    apertura), así que la lista ya no está vacía como antes de ese rediseño.
    """
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")
    async with _client(app) as client:
        response = await client.get("/api/roles")
    assert response.status_code == 200
    roles = response.json()["roles"]
    assert len(roles) == 1
    assert roles[0]["is_admin"] is True


@pytest.mark.asyncio
async def test_loopback_mode_shows_full_admin_sidebar(tmp_path) -> None:
    """`AuthMiddleware` no fija `request.state.is_admin`/`is_instance_admin` en
    loopback (mismo motivo que el test anterior) -- el sidebar debe interpretar
    esa ausencia como "sin restricción" (igual que `require_admin`/
    `require_instance_admin`) y mostrar el bloque Admin completo, no ocultarlo.
    Antes de este fix el bloque entero desaparecía por depender de
    `request.state.user_id is defined`, que tampoco se fija en loopback."""
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")
    async with _client(app) as client:
        response = await client.get("/admin/roles")
    assert response.status_code == 200
    assert '<a class="block text-blue-600 underline" href="/admin/roles">Roles</a>' in response.text
    assert '<a class="block text-blue-600 underline" href="/admin/users">Usuarios</a>' in response.text
    assert _PROYECTOS_ADMIN_LINK in response.text
    assert '<a class="block text-blue-600 underline" href="/admin/tenants">Tenants y usuarios</a>' in response.text
    assert '<a class="block text-blue-600 underline" href="/admin/configuracion-ia">Configuración IA</a>' in response.text
    assert '<a class="block text-blue-600 underline" href="/admin/plantillas-taxonomia">Plantillas de taxonomía</a>' in response.text
    assert "Cerrar sesión" not in response.text
