"""Tests unitarios de AuthStore (revision 8, §2.7.2: auth multi-usuario/multi-tenant)."""

import sqlite3

from datetime import datetime, timedelta, timezone

import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.exceptions import AuthError, TenantAlreadyExistsError, TenantNotFoundError, UserAlreadyExistsError


@pytest.mark.asyncio
async def test_create_tenant_derives_slug_from_name(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")

    assert tenant.id == "acme-corp"
    assert tenant.name == "Acme Corp"


@pytest.mark.asyncio
async def test_create_tenant_rejects_duplicate_slug(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_tenant("Acme Corp")
        with pytest.raises(TenantAlreadyExistsError):
            await store.create_tenant("acme corp")  # normaliza al mismo slug "acme-corp"


@pytest.mark.asyncio
async def test_create_tenant_rejects_empty_name(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        with pytest.raises(AuthError):
            await store.create_tenant("   ")


@pytest.mark.asyncio
async def test_tenant_exists(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_tenant("Acme Corp")
        assert await store.tenant_exists("acme-corp") is True
        assert await store.tenant_exists("no-existe") is False


@pytest.mark.asyncio
async def test_create_user_rejects_unknown_tenant(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        with pytest.raises(TenantNotFoundError):
            await store.create_user("no-existe", "alice", "s3cr3t-password")


@pytest.mark.asyncio
async def test_create_user_password_never_stored_in_plaintext(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    async with AuthStore(db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")

    # Verificacion directa sobre el fichero SQLite: la columna nunca contiene el valor en claro.
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT password_hash, password_salt FROM users WHERE username = 'alice'").fetchone()
    finally:
        conn.close()
    assert row is not None
    password_hash, salt = row
    assert password_hash != "s3cr3t-password"
    assert "s3cr3t-password" not in password_hash
    assert salt and password_hash


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_username_same_tenant_case_insensitive(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")
        with pytest.raises(UserAlreadyExistsError):
            await store.create_user(tenant.id, "ALICE", "another-password")


@pytest.mark.asyncio
async def test_create_user_allows_same_username_in_different_tenants(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        acme = await store.create_tenant("Acme Corp")
        globex = await store.create_tenant("Globex Inc")
        alice_acme = await store.create_user(acme.id, "alice", "s3cr3t-password")
        alice_globex = await store.create_user(globex.id, "alice", "other-password")

    assert alice_acme.id != alice_globex.id
    assert alice_acme.tenant_id != alice_globex.tenant_id


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_username(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        with pytest.raises(AuthError):
            await store.create_user(tenant.id, "alice/../etc", "s3cr3t-password")


@pytest.mark.asyncio
async def test_authenticate_returns_user_on_valid_credentials(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")
        authenticated = await store.authenticate(tenant.id, "alice", "s3cr3t-password")

    assert authenticated is not None
    assert authenticated.username == "alice"


@pytest.mark.asyncio
async def test_authenticate_returns_none_for_wrong_password(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")
        result = await store.authenticate(tenant.id, "alice", "wrong-password")

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_returns_none_for_unknown_username(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        result = await store.authenticate(tenant.id, "no-existe", "cualquier-cosa")

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_returns_none_for_unknown_tenant(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")
        result = await store.authenticate("otro-tenant", "alice", "s3cr3t-password")

    assert result is None


@pytest.mark.asyncio
async def test_create_session_then_get_session_returns_it(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        session = await store.create_session(user)
        fetched = await store.get_session(session.token)

    assert fetched is not None
    assert fetched.token == session.token
    assert fetched.user_id == user.id
    assert fetched.tenant_id == tenant.id


@pytest.mark.asyncio
async def test_get_session_returns_none_for_unknown_token(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        result = await store.get_session("token-inventado")

    assert result is None


@pytest.mark.asyncio
async def test_get_session_returns_none_when_expired(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        session = await store.create_session(user)

        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await store._connection.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?", (expired, session.token)
        )
        await store._connection.commit()

        result = await store.get_session(session.token)

    assert result is None


@pytest.mark.asyncio
async def test_logout_is_selective_other_sessions_of_same_user_survive(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        session_a = await store.create_session(user)  # p.ej. pestana/dispositivo 1
        session_b = await store.create_session(user)  # p.ej. pestana/dispositivo 2

        await store.delete_session(session_a.token)

        after_a = await store.get_session(session_a.token)
        after_b = await store.get_session(session_b.token)

    assert after_a is None
    assert after_b is not None
    assert after_b.token == session_b.token


@pytest.mark.asyncio
async def test_delete_session_unknown_token_is_noop(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.delete_session("token-inventado")  # no debe lanzar
