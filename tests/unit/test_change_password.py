"""Tests del flujo de cambio de contraseña obligatorio (revisión 9).

Usa un usuario normal con `must_change_password=True` (reseteado por un admin),
no la cuenta de fábrica -- esa tiene además el bloqueo de login no-loopback de la
decisión de diseño 1 (rediseño Tenant/Role/User), cubierto aparte en
`test_web_auth.py`.
"""

import httpx
import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig
from doc_organize.web import create_app
from doc_organize.web.auth import SESSION_COOKIE_NAME

_TENANT_NAME = "Acme Corp"
_TENANT_ID = "acme-corp"
_USERNAME = "carol"
_TEMP_PASSWORD = "temp-s3cret-pw"


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


def _non_loopback_app(tmp_path):
    security = SecurityConfig(bind_host="0.0.0.0")
    return create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")


async def _create_user_with_pending_password_change(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant(_TENANT_NAME)
        await store.create_user(tenant.id, _USERNAME, _TEMP_PASSWORD, must_change_password=True)


async def _login(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/login", data={"tenant_id": _TENANT_ID, "username": _USERNAME, "password": _TEMP_PASSWORD})


@pytest.mark.asyncio
async def test_change_password_page_reachable_despite_must_change_password(tmp_path) -> None:
    await _create_user_with_pending_password_change(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/change-password")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current_password_returns_401_and_stays_blocked(tmp_path) -> None:
    await _create_user_with_pending_password_change(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.post(
            "/change-password",
            data={"current_password": "incorrecta", "new_password": "nueva-pw", "confirm_password": "nueva-pw"},
        )
        still_blocked = await client.get("/api/projects")

    assert response.status_code == 401
    assert still_blocked.status_code == 403


@pytest.mark.asyncio
async def test_change_password_mismatched_confirmation_returns_422(tmp_path) -> None:
    await _create_user_with_pending_password_change(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.post(
            "/change-password",
            data={"current_password": _TEMP_PASSWORD, "new_password": "nueva-pw", "confirm_password": "otra-cosa"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_success_unblocks_the_rest_of_the_app(tmp_path) -> None:
    await _create_user_with_pending_password_change(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        response = await client.post(
            "/change-password",
            data={"current_password": _TEMP_PASSWORD, "new_password": "nueva-pw-elegida", "confirm_password": "nueva-pw-elegida"},
        )
        unblocked = await client.get("/api/projects")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert unblocked.status_code == 200


@pytest.mark.asyncio
async def test_new_password_works_on_next_login(tmp_path) -> None:
    await _create_user_with_pending_password_change(tmp_path)
    app = _non_loopback_app(tmp_path)
    async with _client(app) as client:
        await _login(client)
        await client.post(
            "/change-password",
            data={"current_password": _TEMP_PASSWORD, "new_password": "nueva-pw-elegida", "confirm_password": "nueva-pw-elegida"},
        )
        await client.post("/logout")
        relogin = await client.post("/login", data={"tenant_id": _TENANT_ID, "username": _USERNAME, "password": "nueva-pw-elegida"})
        no_longer_blocked = await client.get("/api/projects")

    assert SESSION_COOKIE_NAME in relogin.cookies
    assert no_longer_blocked.status_code == 200
