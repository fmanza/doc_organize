"""Tests unitarios de AuthStore (revision 8, §2.7.2: auth multi-usuario/multi-tenant)."""

import sqlite3

from datetime import datetime, timedelta, timezone

import pytest

from doc_organize.auth import AuthStore
from doc_organize.core.constants import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME
from doc_organize.core.exceptions import (
    AuthError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
)


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


# ===== Roles y usuarios (revision 9) =====


@pytest.mark.asyncio
async def test_create_tenant_bootstraps_admin_role_and_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")

        roles = await store.list_roles(tenant.id)
        assert len(roles) == 1
        assert roles[0].name == "admin"
        assert roles[0].is_admin is True
        assert roles[0].project_names == []

        users = await store.list_users(tenant.id)
        assert len(users) == 1
        assert users[0].username == DEFAULT_ADMIN_USERNAME
        assert users[0].role_id == roles[0].id
        assert users[0].must_change_password is True

        authenticated = await store.authenticate(tenant.id, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
    assert authenticated is not None
    assert authenticated.must_change_password is True


@pytest.mark.asyncio
async def test_create_user_without_role_id_defaults_to_admin_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = (await store.list_roles(tenant.id))[0]
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")

    assert user.role_id == admin_role.id
    assert user.must_change_password is False


@pytest.mark.asyncio
async def test_create_role_rejects_admin_with_project_names(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        with pytest.raises(AuthError):
            await store.create_role(tenant.id, "Super Admin", is_admin=True, project_names=["Proyecto A"])


@pytest.mark.asyncio
async def test_create_role_rejects_duplicate_name_case_insensitive(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_role(tenant.id, "Lector")
        with pytest.raises(RoleAlreadyExistsError):
            await store.create_role(tenant.id, "LECTOR")


@pytest.mark.asyncio
async def test_create_role_rejects_admin_with_scan_roots(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        with pytest.raises(AuthError):
            await store.create_role(tenant.id, "Super Admin", is_admin=True, allowed_scan_roots=["/repo"])


@pytest.mark.asyncio
async def test_create_role_default_has_no_allowed_scan_roots(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A"])
    assert role.allowed_scan_roots == []


@pytest.mark.asyncio
async def test_create_role_with_allowed_scan_roots(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(
            tenant.id, "Lector", project_names=["Proyecto A"], allowed_scan_roots=["/repo/entrada"]
        )
        fetched = await store.get_role(tenant.id, role.id)
    assert role.allowed_scan_roots == ["/repo/entrada"]
    assert fetched.allowed_scan_roots == ["/repo/entrada"]


@pytest.mark.asyncio
async def test_update_role_replaces_scan_roots(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", allowed_scan_roots=["/repo/a"])
        updated = await store.update_role(tenant.id, role.id, allowed_scan_roots=["/repo/b"])
    assert updated.allowed_scan_roots == ["/repo/b"]


@pytest.mark.asyncio
async def test_update_role_rejects_admin_with_scan_roots(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", allowed_scan_roots=["/repo/a"])
        with pytest.raises(AuthError):
            await store.update_role(tenant.id, role.id, is_admin=True, project_names=[])


@pytest.mark.asyncio
async def test_create_role_with_restricted_projects(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A", "Proyecto B"])

    assert role.is_admin is False
    assert sorted(role.project_names) == ["Proyecto A", "Proyecto B"]


@pytest.mark.asyncio
async def test_can_access_project_admin_role_sees_everything(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = (await store.list_roles(tenant.id))[0]
        allowed = await store.can_access_project(tenant.id, admin_role.id, "Cualquier Proyecto")
    assert allowed is True


@pytest.mark.asyncio
async def test_can_access_project_restricted_role_only_sees_its_list(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A"])
        allowed_a = await store.can_access_project(tenant.id, role.id, "proyecto a")  # case-insensitive
        allowed_b = await store.can_access_project(tenant.id, role.id, "Proyecto B")
    assert allowed_a is True
    assert allowed_b is False


@pytest.mark.asyncio
async def test_update_role_replaces_project_list(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A"])
        updated = await store.update_role(tenant.id, role.id, project_names=["Proyecto B"])
    assert updated.project_names == ["Proyecto B"]


@pytest.mark.asyncio
async def test_delete_role_rejects_when_assigned_to_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector")
        await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        with pytest.raises(RoleInUseError):
            await store.delete_role(tenant.id, role.id)


@pytest.mark.asyncio
async def test_delete_role_rejects_last_admin_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = (await store.list_roles(tenant.id))[0]
        with pytest.raises(RoleInUseError):
            await store.delete_role(tenant.id, admin_role.id)


@pytest.mark.asyncio
async def test_delete_role_allows_second_unused_admin_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        second_admin = await store.create_role(tenant.id, "Super Admin", is_admin=True)
        await store.delete_role(tenant.id, second_admin.id)  # no debe lanzar
        with pytest.raises(RoleNotFoundError):
            await store.get_role(tenant.id, second_admin.id)


@pytest.mark.asyncio
async def test_update_user_resets_password_sets_must_change_password(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        updated = await store.update_user(tenant.id, user.id, password="nueva-password")

        old_still_works = await store.authenticate(tenant.id, "alice", "s3cr3t-password")
        new_works = await store.authenticate(tenant.id, "alice", "nueva-password")

    assert updated.must_change_password is True
    assert old_still_works is None
    assert new_works is not None


@pytest.mark.asyncio
async def test_update_user_rejects_removing_last_admin_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_user = (await store.list_users(tenant.id))[0]
        member_role = await store.create_role(tenant.id, "Miembro")
        with pytest.raises(RoleInUseError):
            await store.update_user(tenant.id, admin_user.id, role_id=member_role.id)


@pytest.mark.asyncio
async def test_delete_user_rejects_last_admin_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_user = (await store.list_users(tenant.id))[0]
        with pytest.raises(RoleInUseError):
            await store.delete_user(tenant.id, admin_user.id)


@pytest.mark.asyncio
async def test_delete_user_allows_second_admin_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = (await store.list_roles(tenant.id))[0]
        second_admin = await store.create_user(tenant.id, "bob", "s3cr3t-password", role_id=admin_role.id)
        await store.delete_user(tenant.id, second_admin.id)  # no debe lanzar
        with pytest.raises(UserNotFoundError):
            await store.get_user(tenant.id, second_admin.id)


@pytest.mark.asyncio
async def test_change_password_wrong_current_password_fails(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        success = await store.change_password(user.id, "contraseña-incorrecta", "nueva-password")
    assert success is False


@pytest.mark.asyncio
async def test_change_password_success_clears_must_change_password(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        success = await store.change_password(
            (await store.list_users(tenant.id))[0].id, DEFAULT_ADMIN_PASSWORD, "nueva-password-admin"
        )
        authenticated = await store.authenticate(tenant.id, DEFAULT_ADMIN_USERNAME, "nueva-password-admin")

    assert success is True
    assert authenticated is not None
    assert authenticated.must_change_password is False


@pytest.mark.asyncio
async def test_get_session_with_access_resolves_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A"])
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(user)
        resolved = await store.get_session_with_access(session.token)

    assert resolved is not None
    assert resolved.role_id == role.id
    assert resolved.is_admin is False
    assert resolved.must_change_password is False


@pytest.mark.asyncio
async def test_migration_backfills_users_without_role_to_admin_role(tmp_path) -> None:
    """Simula una base `auth.db` creada antes de la revisión 9 (sin `role_id`/
    `must_change_password` en `users`, sin tablas `roles`/`role_projects`), abierta
    de nuevo tras la migración: el usuario preexistente debe quedar con acceso
    admin (nunca reducido), no huérfano.
    """
    import sqlite3

    from datetime import datetime, timezone
    from uuid import uuid4

    db_path = tmp_path / "auth.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE users (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, username TEXT NOT NULL,
                password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO tenants (id, name, created_at) VALUES ('acme-corp', 'Acme Corp', ?)", (now,))
        conn.execute(
            "INSERT INTO users (id, tenant_id, username, password_hash, password_salt, created_at) "
            "VALUES (?, 'acme-corp', 'alice', 'x', 'y', ?)",
            (str(uuid4()), now),
        )
        conn.commit()
    finally:
        conn.close()

    async with AuthStore(db_path) as store:
        users = await store.list_users("acme-corp")
        assert len(users) == 1
        assert users[0].role_id is not None

        role = await store.get_role("acme-corp", users[0].role_id)
        assert role.is_admin is True


# ===== Condición de carrera en la comprobación de duplicados (revisión 9, sub-paso 2) =====
#
# El pre-check (`tenant_exists`/`_role_name_taken`/`_username_taken`) no es la única
# defensa contra duplicados: dos peticiones concurrentes con el mismo nombre podrían
# pasar ambas el pre-check antes de que ninguna haga commit. Se fuerza esa ventana
# monkeypracheando el pre-check para que mienta ("no existe") aunque el registro ya
# esté insertado — así se ejerce el camino real de defensa: el índice UNIQUE/PK del
# esquema + la captura de `IntegrityError` en el INSERT.


@pytest.mark.asyncio
async def test_create_tenant_race_condition_raises_clean_error_not_raw_integrity_error(tmp_path, monkeypatch) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_tenant("Acme Corp")

        async def _lying_tenant_exists(_tenant_id: str) -> bool:
            return False

        monkeypatch.setattr(store, "tenant_exists", _lying_tenant_exists)

        with pytest.raises(TenantAlreadyExistsError):
            await store.create_tenant("Acme Corp")


@pytest.mark.asyncio
async def test_create_role_race_condition_raises_clean_error_not_raw_integrity_error(tmp_path, monkeypatch) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_role(tenant.id, "Lector")

        async def _lying_role_name_taken(_tenant_id: str, _name: str) -> bool:
            return False

        monkeypatch.setattr(store, "_role_name_taken", _lying_role_name_taken)

        with pytest.raises(RoleAlreadyExistsError):
            await store.create_role(tenant.id, "Lector")


@pytest.mark.asyncio
async def test_create_user_race_condition_raises_clean_error_not_raw_integrity_error(tmp_path, monkeypatch) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")

        async def _lying_username_taken(_tenant_id: str, _username: str) -> bool:
            return False

        monkeypatch.setattr(store, "_username_taken", _lying_username_taken)

        with pytest.raises(UserAlreadyExistsError):
            await store.create_user(tenant.id, "alice", "otra-password")


# ===== Degradar is_admin sin project_names explícito (revisión 9, sub-paso 2) =====


@pytest.mark.asyncio
async def test_update_role_demote_admin_without_project_names_raises(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Super Admin", is_admin=True)
        with pytest.raises(AuthError):
            await store.update_role(tenant.id, role.id, is_admin=False)


@pytest.mark.asyncio
async def test_update_role_demote_admin_with_explicit_empty_project_names_succeeds(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Super Admin", is_admin=True)
        updated = await store.update_role(tenant.id, role.id, is_admin=False, project_names=[])

    assert updated.is_admin is False
    assert updated.project_names == []


@pytest.mark.asyncio
async def test_update_role_demote_admin_with_project_names_succeeds(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Super Admin", is_admin=True)
        updated = await store.update_role(tenant.id, role.id, is_admin=False, project_names=["Proyecto A"])

    assert updated.is_admin is False
    assert updated.project_names == ["Proyecto A"]


@pytest.mark.asyncio
async def test_update_role_setting_is_admin_true_does_not_require_project_names(tmp_path) -> None:
    """La nueva regla solo se aplica al degradar (True -> False); promover a admin
    sigue sin exigir `project_names` (de hecho, rechazaría una lista no vacía)."""
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A"])
        updated = await store.update_role(tenant.id, role.id, is_admin=True, project_names=[])

    assert updated.is_admin is True
    assert updated.project_names == []
