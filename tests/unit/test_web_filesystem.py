"""Tests del explorador de carpetas del servidor (botón "Buscar…" del menú Escaneo)."""

import httpx
import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig
from doc_organize.web import create_app
from doc_organize.web.auth import SESSION_COOKIE_NAME


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


@pytest.mark.asyncio
async def test_browse_lists_subfolders(tmp_path) -> None:
    (tmp_path / "b-folder").mkdir()
    (tmp_path / "a-folder").mkdir()
    (tmp_path / "a-file.txt").write_text("x", encoding="utf-8")
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        response = await client.get("/api/fs/browse", params={"path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_path"] == str(tmp_path.resolve())
    assert payload["entries"] == ["a-folder", "b-folder"]  # ordenado, solo carpetas


@pytest.mark.asyncio
async def test_browse_reports_parent_path(tmp_path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        response = await client.get("/api/fs/browse", params={"path": str(child)})

    assert response.status_code == 200
    assert response.json()["parent_path"] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_browse_404_for_nonexistent_path(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        response = await client.get("/api/fs/browse", params={"path": str(tmp_path / "no-existe")})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_browse_defaults_to_home_directory(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        response = await client.get("/api/fs/browse")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_browse_non_admin_role_rejects_path_outside_allowed_roots(tmp_path) -> None:
    """Misma restricción `allowed_scan_roots` que el escaneo: un rol restringido
    no puede explorar fuera de sus raíces permitidas."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        allowed_root = tmp_path / "allowed-root"
        allowed_root.mkdir()
        role = await store.create_role(tenant.id, "Lector", allowed_scan_roots=[str(allowed_root)])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    outside = tmp_path / "outside"
    outside.mkdir()
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=auth_db_path)

    async with _client(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, session.token)
        response = await client.get("/api/fs/browse", params={"path": str(outside)})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_browse_non_admin_role_allows_path_inside_allowed_roots(tmp_path) -> None:
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        allowed_root = tmp_path / "allowed-root"
        allowed_root.mkdir()
        role = await store.create_role(tenant.id, "Lector", allowed_scan_roots=[str(allowed_root)])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=auth_db_path)

    async with _client(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, session.token)
        response = await client.get("/api/fs/browse", params={"path": str(allowed_root)})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_browse_non_admin_role_rejects_nonexistent_path_outside_allowed_roots_with_403_not_404(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-03/04): antes se comprobaba `is_dir()` antes que
    `allowed_scan_roots` — un rol restringido podía distinguir "existe pero no
    tengo acceso" (403) de "no existe" (404) para CUALQUIER ruta del servidor,
    incluidas las que ni siquiera existen. Ahora la autorización se comprueba
    primero, así que una ruta inexistente fuera del ámbito del rol da 403, no 404
    (que revelaría que sí se llegó a mirar si existía)."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        allowed_root = tmp_path / "allowed-root"
        allowed_root.mkdir()
        role = await store.create_role(tenant.id, "Lector", allowed_scan_roots=[str(allowed_root)])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    nonexistent_outside = tmp_path / "no-existe-y-fuera-de-ambito"
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=tmp_path / "projects.json", auth_db_path=auth_db_path)

    async with _client(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, session.token)
        response = await client.get("/api/fs/browse", params={"path": str(nonexistent_outside)})

    assert response.status_code == 403
