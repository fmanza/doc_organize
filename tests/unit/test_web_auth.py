"""Tests de autenticación multi-usuario y multi-tenant (revisión 8, §2.7.2).

Suite de acceso no-loopback vía sesión (cookie tras `/login`) — reemplaza la suite
basada en bearer token compartido de la revisión 2/7 (§2.7.1, ❌ SUPERSEDIDO), que
vivía en `test_web_app.py`.
"""

import httpx
import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig
from doc_organize.web import create_app
from doc_organize.web.auth import SESSION_COOKIE_NAME

_TENANT_NAME = "Acme Corp"
_TENANT_ID = "acme-corp"
_USERNAME = "alice"
_PASSWORD = "s3cr3t-password"


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _provision_user(auth_db_path, tenant_name: str = _TENANT_NAME, username: str = _USERNAME, password: str = _PASSWORD) -> str:
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant(tenant_name)
        await store.create_user(tenant.id, username, password)
    return tenant.id


def _non_loopback_app(tmp_path):
    security = SecurityConfig(bind_host="0.0.0.0")
    return create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")


async def _login(client: httpx.AsyncClient, tenant_id: str = _TENANT_ID, username: str = _USERNAME, password: str = _PASSWORD) -> httpx.Response:
    return await client.post("/login", data={"tenant_id": tenant_id, "username": username, "password": password})


# ===== GET /login, POST /login, POST /logout =====


@pytest.mark.asyncio
async def test_login_page_loads_without_session(tmp_path) -> None:
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await client.get("/login")
    assert response.status_code == 200
    assert "Iniciar sesión" in response.text


@pytest.mark.asyncio
async def test_login_with_valid_credentials_sets_cookie_and_redirects(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await _login(client)

    assert response.status_code in (200, 303)
    assert SESSION_COOKIE_NAME in response.cookies
    cookie = response.cookies[SESSION_COOKIE_NAME]
    assert cookie  # opaco, no es la contraseña ni el token de ninguna otra sesion


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401_without_cookie(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await _login(client, password="contraseña-incorrecta")

    assert response.status_code == 401
    assert SESSION_COOKIE_NAME not in response.cookies


@pytest.mark.asyncio
async def test_login_with_unknown_username_returns_same_401_as_wrong_password(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await _login(client, username="no-existe")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_cookie_not_marked_secure_over_plain_http(tmp_path) -> None:
    # Revision de seguridad (revision 9): `secure` solo cuando la peticion es https,
    # para que la cookie siga funcionando sobre HTTP puro (loopback local, tests).
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await _login(client)
    assert "secure" not in response.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_login_cookie_marked_secure_over_https(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app, base_url="https://example.com") as client:
        response = await _login(client)
    assert "secure" in response.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_login_locks_out_after_repeated_failures(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        for _ in range(5):
            response = await _login(client, password="contraseña-incorrecta")
            assert response.status_code == 401

        locked = await _login(client, password="contraseña-incorrecta")
        assert locked.status_code == 429

        # Ni siquiera la contraseña correcta pasa mientras dure el bloqueo.
        still_locked = await _login(client)
        assert still_locked.status_code == 429


@pytest.mark.asyncio
async def test_login_success_resets_failure_counter(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        for _ in range(4):
            await _login(client, password="contraseña-incorrecta")

        success = await _login(client)
        assert success.status_code == 303

        after_reset = await _login(client, password="contraseña-incorrecta")
        assert after_reset.status_code == 401  # no 429: el contador se limpio tras el exito


@pytest.mark.asyncio
async def test_login_with_unknown_tenant_returns_same_401(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await _login(client, tenant_id="otro-tenant")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_deletes_cookie_and_subsequent_request_redirects(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        assert (await client.get("/api/projects")).status_code == 200

        await client.post("/logout")
        response = await client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_login_and_logout_paths_exempt_from_auth(tmp_path) -> None:
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        get_login = await client.get("/login")
        post_logout = await client.post("/logout", follow_redirects=False)

    assert get_login.status_code == 200
    assert post_logout.status_code == 303  # redirige a /login, no 401


# ===== Acceso no-loopback a /api/* y paginas, con/sin sesion =====


@pytest.mark.asyncio
async def test_non_loopback_get_without_session_returns_401(tmp_path) -> None:
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await client.get("/api/projects")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_loopback_get_with_valid_session_returns_200(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/api/projects")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_loopback_get_with_invalid_session_cookie_returns_401(tmp_path) -> None:
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, "token-inventado")
        response = await client.get("/api/projects")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_loopback_page_route_without_session_redirects_to_login(tmp_path) -> None:
    # Revision 8 (SS2.7.2): a diferencia de la revision 7 (SUPERSEDIDO), las paginas
    # HTML SI exigen sesion en host no-loopback.
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_non_loopback_page_route_with_valid_session_returns_200(tmp_path) -> None:
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_loopback_write_with_mismatched_origin_returns_403(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app, base_url="http://example.com") as client:
        await _login(client)
        response = await client.post(
            "/api/projects",
            json={"name": "Proyecto", "base_location": str(base)},
            headers={"Origin": "http://attacker.com"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_non_loopback_write_with_matching_origin_succeeds(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app, base_url="http://example.com") as client:
        await _login(client)
        response = await client.post(
            "/api/projects",
            json={"name": "Proyecto", "base_location": str(base)},
            headers={"Origin": "http://example.com"},
        )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_non_loopback_write_without_origin_header_succeeds(tmp_path) -> None:
    # Clientes no-navegador (curl, scripts) no envian Origin; la sesion basta.
    base = tmp_path / "workspaces"
    base.mkdir()
    await _provision_user(tmp_path / "auth.db")
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.post(
            "/api/projects",
            json={"name": "Proyecto", "base_location": str(base)},
        )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_non_loopback_bearer_header_alone_no_longer_authenticates(tmp_path) -> None:
    # Revision 8 (SS2.7.2): el bearer compartido se retira. Un header Authorization
    # sin cookie de sesion no debe autenticar nada.
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        response = await client.get("/api/projects", headers={"Authorization": "Bearer cualquier-cosa"})
    assert response.status_code == 401


# ===== Aislamiento multi-tenant vía HTTP (revision 8, SS2.7.2, checklist SS9.6.2) =====


@pytest.mark.asyncio
async def test_users_of_different_tenants_only_see_their_own_projects(tmp_path) -> None:
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        acme = await store.create_tenant("Acme Corp")
        globex = await store.create_tenant("Globex Inc")
        await store.create_user(acme.id, "alice", "s3cr3t-password")
        await store.create_user(globex.id, "bob", "other-password")

    base = tmp_path / "workspaces"
    base.mkdir()
    app = _non_loopback_app(tmp_path)

    async with _client(app) as alice_client:
        await _login(alice_client, tenant_id=acme.id, username="alice", password="s3cr3t-password")
        await alice_client.post("/api/projects", json={"name": "Proyecto Acme", "base_location": str(base)})

    async with _client(app) as bob_client:
        await _login(bob_client, tenant_id=globex.id, username="bob", password="other-password")
        await bob_client.post("/api/projects", json={"name": "Proyecto Globex", "base_location": str(base)})

        bob_projects = (await bob_client.get("/api/projects")).json()["projects"]

    async with _client(app) as alice_client_again:
        await _login(alice_client_again, tenant_id=acme.id, username="alice", password="s3cr3t-password")
        alice_projects = (await alice_client_again.get("/api/projects")).json()["projects"]

    assert [p["name"] for p in alice_projects] == ["Proyecto Acme"]
    assert [p["name"] for p in bob_projects] == ["Proyecto Globex"]
