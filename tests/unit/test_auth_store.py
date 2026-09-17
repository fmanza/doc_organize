"""Tests unitarios de AuthStore (revision 8, §2.7.2: auth multi-usuario/multi-tenant;
rediseño Tenant/Role/User: bootstrap de fábrica, Role global, is_blocked/is_instance_admin)."""

import sqlite3

from datetime import UTC, datetime, timedelta

import pytest

from doc_organize.auth import AuthStore, is_factory_admin_account
from doc_organize.core.constants import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, DEFAULT_TENANT_ID
from doc_organize.core.exceptions import (
    AuthError,
    InstanceAdminRequiredError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    TenantAlreadyExistsError,
    TenantInUseError,
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
async def test_authenticate_returns_none_for_blocked_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        await store.set_user_blocked(tenant.id, user.id, True)
        result = await store.authenticate(tenant.id, "alice", "s3cr3t-password")

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

        expired = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await store._session_store._connection.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (expired, session.token))
        await store._session_store._connection.commit()

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


# ===== Bootstrap de fábrica del tenant por defecto (rediseño Tenant/Role/User) =====


@pytest.mark.asyncio
async def test_opening_auth_store_bootstraps_default_tenant_admin_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        assert await store.tenant_exists(DEFAULT_TENANT_ID) is True

        users = await store.list_users(DEFAULT_TENANT_ID)
        assert len(users) == 1
        admin_user = users[0]
        assert admin_user.username == DEFAULT_ADMIN_USERNAME
        assert admin_user.must_change_password is True
        assert admin_user.is_instance_admin is True
        assert admin_user.is_blocked is False

        role = await store.get_role(admin_user.role_id)
        assert role.is_admin is True

        authenticated = await store.authenticate(DEFAULT_TENANT_ID, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
    assert authenticated is not None
    assert is_factory_admin_account(authenticated) is True


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_across_reopens(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    async with AuthStore(db_path) as store:
        pass
    async with AuthStore(db_path) as store:
        users = await store.list_users(DEFAULT_TENANT_ID)
    assert len(users) == 1  # no se duplica el usuario admin de fábrica al reabrir


@pytest.mark.asyncio
async def test_is_factory_admin_account_false_for_other_users(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", must_change_password=True)
        default_users = await store.list_users(DEFAULT_TENANT_ID)
        admin_but_password_changed = await store.change_password(default_users[0].id, DEFAULT_ADMIN_PASSWORD, "otra-cosa")
        changed_admin = await store.get_user(DEFAULT_TENANT_ID, default_users[0].id)

    assert is_factory_admin_account(alice) is False  # tenant distinto
    assert admin_but_password_changed is True
    assert is_factory_admin_account(changed_admin) is False  # ya cambió la contraseña


@pytest.mark.asyncio
async def test_create_tenant_no_longer_bootstraps_role_or_user(tmp_path) -> None:
    """Rediseño Tenant/Role/User: `create_tenant` (para cualquier tenant que no sea
    el por defecto) ya no crea ningún rol ni usuario -- `Role` no está ligado a un
    tenant, así que no hay "rol admin de ESTE tenant" que aprovisionar."""
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        users = await store.list_users(tenant.id)
    assert users == []


# ===== Tenants (listar/eliminar, rediseño Tenant/Role/User) =====


@pytest.mark.asyncio
async def test_list_tenants_includes_default_and_created(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_tenant("Acme Corp")
        tenants = await store.list_tenants()
    ids = {tenant.id for tenant in tenants}
    assert ids == {DEFAULT_TENANT_ID, "acme-corp"}


@pytest.mark.asyncio
async def test_delete_tenant_rejects_unknown_tenant(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        with pytest.raises(TenantNotFoundError):
            await store.delete_tenant("no-existe", has_projects=False)


@pytest.mark.asyncio
async def test_delete_tenant_rejects_with_users(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")
        with pytest.raises(TenantInUseError):
            await store.delete_tenant(tenant.id, has_projects=False)


@pytest.mark.asyncio
async def test_delete_tenant_rejects_with_projects(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        with pytest.raises(TenantInUseError):
            await store.delete_tenant(tenant.id, has_projects=True)


@pytest.mark.asyncio
async def test_delete_tenant_succeeds_when_empty(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.delete_tenant(tenant.id, has_projects=False)
        assert await store.tenant_exists(tenant.id) is False


@pytest.mark.asyncio
async def test_deleting_default_tenant_gets_recreated_on_next_open(tmp_path) -> None:
    """Nivel 3 punto 6 del rediseño: DEFAULT_TENANT_ID no es un caso especial en
    código -- se puede borrar igual que cualquier otro (vacío), y el bootstrap lo
    vuelve a crear de fábrica (con un usuario admin nuevo) la siguiente vez que se
    abra `AuthStore`, sin dejar nunca la instalación sin ninguna forma de entrar."""
    db_path = tmp_path / "auth.db"
    async with AuthStore(db_path) as store:
        default_users = await store.list_users(DEFAULT_TENANT_ID)
        await store.delete_user(DEFAULT_TENANT_ID, default_users[0].id)
        await store.delete_tenant(DEFAULT_TENANT_ID, has_projects=False)
        assert await store.tenant_exists(DEFAULT_TENANT_ID) is False

    async with AuthStore(db_path) as store:
        assert await store.tenant_exists(DEFAULT_TENANT_ID) is True
        recreated_users = await store.list_users(DEFAULT_TENANT_ID)
        assert len(recreated_users) == 1
        assert recreated_users[0].username == DEFAULT_ADMIN_USERNAME
        assert recreated_users[0].must_change_password is True


# ===== Roles (globales, rediseño Tenant/Role/User) =====


@pytest.mark.asyncio
async def test_create_user_without_role_id_defaults_to_admin_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")

    assert user.role_id == admin_role.id
    assert user.must_change_password is False


@pytest.mark.asyncio
async def test_create_role_rejects_admin_with_project_names(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        with pytest.raises(AuthError):
            await store.create_role("Super Admin", is_admin=True, project_names=["Proyecto A"])


@pytest.mark.asyncio
async def test_create_role_rejects_duplicate_name_case_insensitive(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_role("Lector")
        with pytest.raises(RoleAlreadyExistsError):
            await store.create_role("LECTOR")


@pytest.mark.asyncio
async def test_create_role_with_restricted_projects(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Lector", project_names=["Proyecto A", "Proyecto B"])

    assert role.is_admin is False
    assert sorted(role.project_names) == ["Proyecto A", "Proyecto B"]


@pytest.mark.asyncio
async def test_role_is_shared_across_tenants(tmp_path) -> None:
    """Un rol ya no está ligado a un tenant: puede asignarse a usuarios de tenants
    distintos (rediseño Tenant/Role/User)."""
    async with AuthStore(tmp_path / "auth.db") as store:
        acme = await store.create_tenant("Acme Corp")
        globex = await store.create_tenant("Globex Inc")
        role = await store.create_role("Lector", project_names=["Proyecto A"])
        alice = await store.create_user(acme.id, "alice", "s3cr3t-password", role_id=role.id)
        bob = await store.create_user(globex.id, "bob", "s3cr3t-password", role_id=role.id)

        assigned = await store.users_for_role(role.id)

    assigned_ids = {user.id for user in assigned}
    assert assigned_ids == {alice.id, bob.id}


@pytest.mark.asyncio
async def test_can_access_project_admin_role_sees_everything(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        allowed = await store.can_access_project(admin_role.id, "Cualquier Proyecto")
    assert allowed is True


@pytest.mark.asyncio
async def test_can_access_project_restricted_role_only_sees_its_list(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Lector", project_names=["Proyecto A"])
        allowed_a = await store.can_access_project(role.id, "proyecto a")  # case-insensitive
        allowed_b = await store.can_access_project(role.id, "Proyecto B")
    assert allowed_a is True
    assert allowed_b is False


@pytest.mark.asyncio
async def test_can_access_project_unknown_role_returns_false(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        allowed = await store.can_access_project("no-existe", "Proyecto A")
    assert allowed is False


@pytest.mark.asyncio
async def test_update_role_replaces_project_list(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Lector", project_names=["Proyecto A"])
        updated = await store.update_role(role.id, project_names=["Proyecto B"])
    assert updated.project_names == ["Proyecto B"]


@pytest.mark.asyncio
async def test_delete_role_rejects_when_assigned_to_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role("Lector")
        await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        with pytest.raises(RoleInUseError):
            await store.delete_role(role.id)


@pytest.mark.asyncio
async def test_delete_role_rejects_last_admin_role_in_the_system(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        with pytest.raises(RoleInUseError):
            await store.delete_role(admin_role.id)


@pytest.mark.asyncio
async def test_delete_role_allows_second_unused_admin_role(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        second_admin = await store.create_role("Super Admin", is_admin=True)
        await store.delete_role(second_admin.id)  # no debe lanzar
        with pytest.raises(RoleNotFoundError):
            await store.get_role(second_admin.id)


@pytest.mark.asyncio
async def test_update_role_demote_admin_without_project_names_raises(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Super Admin", is_admin=True)
        with pytest.raises(AuthError):
            await store.update_role(role.id, is_admin=False)


@pytest.mark.asyncio
async def test_update_role_demote_admin_with_explicit_empty_project_names_succeeds(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Super Admin", is_admin=True)
        updated = await store.update_role(role.id, is_admin=False, project_names=[])

    assert updated.is_admin is False
    assert updated.project_names == []


@pytest.mark.asyncio
async def test_update_role_demote_admin_with_project_names_succeeds(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Super Admin", is_admin=True)
        updated = await store.update_role(role.id, is_admin=False, project_names=["Proyecto A"])

    assert updated.is_admin is False
    assert updated.project_names == ["Proyecto A"]


@pytest.mark.asyncio
async def test_update_role_setting_is_admin_true_does_not_require_project_names(tmp_path) -> None:
    """La regla solo se aplica al degradar (True -> False); promover a admin sigue
    sin exigir `project_names` (de hecho, rechazaría una lista no vacía)."""
    async with AuthStore(tmp_path / "auth.db") as store:
        role = await store.create_role("Lector", project_names=["Proyecto A"])
        updated = await store.update_role(role.id, is_admin=True, project_names=[])

    assert updated.is_admin is True
    assert updated.project_names == []


# ===== Usuarios: rol, contraseña, bloqueo (revision 9; rediseño Tenant/Role/User) =====


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
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        admin_user = await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        member_role = await store.create_role("Miembro")
        # Un segundo usuario (no-admin) del tenant: sin él, demoter al único admin
        # vaciaría el tenant del todo (estado terminal permitido, ver
        # `_count_other_users`) en vez de dejar a alguien desatendido.
        await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=member_role.id)
        with pytest.raises(RoleInUseError):
            await store.update_user(tenant.id, admin_user.id, role_id=member_role.id)


@pytest.mark.asyncio
async def test_update_user_allows_demoting_sole_admin_when_they_are_the_only_user(tmp_path) -> None:
    """Vaciar el tenant de admins es legítimo si el admin es el ÚNICO usuario del
    tenant: no deja a nadie desatendido (ver `_count_other_users`)."""
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        admin_user = await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        member_role = await store.create_role("Miembro")
        updated = await store.update_user(tenant.id, admin_user.id, role_id=member_role.id)  # no debe lanzar
    assert updated.role_id == member_role.id


@pytest.mark.asyncio
async def test_delete_user_rejects_last_admin_user_of_tenant(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        admin_user = await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        member_role = await store.create_role("Miembro")
        await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=member_role.id)
        with pytest.raises(RoleInUseError):
            await store.delete_user(tenant.id, admin_user.id)


@pytest.mark.asyncio
async def test_delete_user_allows_deleting_sole_admin_when_they_are_the_only_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        admin_user = await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        await store.delete_user(tenant.id, admin_user.id)  # no debe lanzar: vacía el tenant por completo
        assert await store.list_users(tenant.id) == []


@pytest.mark.asyncio
async def test_delete_user_allows_second_admin_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=admin_role.id)
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
        default_admin = (await store.list_users(DEFAULT_TENANT_ID))[0]
        success = await store.change_password(default_admin.id, DEFAULT_ADMIN_PASSWORD, "nueva-password-admin")
        authenticated = await store.authenticate(DEFAULT_TENANT_ID, DEFAULT_ADMIN_USERNAME, "nueva-password-admin")

    assert success is True
    assert authenticated is not None
    assert authenticated.must_change_password is False


@pytest.mark.asyncio
async def test_get_session_with_access_resolves_role_and_instance_admin(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role("Lector", project_names=["Proyecto A"])
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(user)
        resolved = await store.get_session_with_access(session.token)

    assert resolved is not None
    assert resolved.role_id == role.id
    assert resolved.is_admin is False
    assert resolved.must_change_password is False
    assert resolved.is_instance_admin is False


# ===== is_blocked: invalidación de sesión (Nivel 2, rediseño Tenant/Role/User) =====


@pytest.mark.asyncio
async def test_set_user_blocked_invalidates_active_sessions(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        session = await store.create_session(user)

        await store.set_user_blocked(tenant.id, user.id, True)

        still_valid = await store.get_session(session.token)
    assert still_valid is None


@pytest.mark.asyncio
async def test_set_user_blocked_false_does_not_touch_other_sessions(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        bob = await store.create_user(tenant.id, "bob", "s3cr3t-password")
        session_bob = await store.create_session(bob)

        await store.set_user_blocked(tenant.id, alice.id, True)

        assert await store.get_session(session_bob.token) is not None


@pytest.mark.asyncio
async def test_set_user_blocked_rejects_last_active_admin_of_tenant(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        admin_user = await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        member_role = await store.create_role("Miembro")
        await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=member_role.id)
        with pytest.raises(RoleInUseError):
            await store.set_user_blocked(tenant.id, admin_user.id, True)


@pytest.mark.asyncio
async def test_set_user_blocked_allows_blocking_sole_admin_when_they_are_the_only_user(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        admin_user = await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        blocked = await store.set_user_blocked(tenant.id, admin_user.id, True)  # no debe lanzar
    assert blocked.is_blocked is True


@pytest.mark.asyncio
async def test_set_user_blocked_allows_blocking_second_admin(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        admin_role = next(role for role in await store.list_roles() if role.is_admin)
        await store.create_user(tenant.id, "admin", "s3cr3t-password", role_id=admin_role.id)
        second_admin = await store.create_user(tenant.id, "bob", "s3cr3t-password", role_id=admin_role.id)
        blocked = await store.set_user_blocked(tenant.id, second_admin.id, True)  # no debe lanzar
    assert blocked.is_blocked is True


@pytest.mark.asyncio
async def test_blocked_user_cannot_authenticate_but_can_be_unblocked(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        await store.set_user_blocked(tenant.id, user.id, True)
        assert await store.authenticate(tenant.id, "alice", "s3cr3t-password") is None

        await store.set_user_blocked(tenant.id, user.id, False)
        assert await store.authenticate(tenant.id, "alice", "s3cr3t-password") is not None


# ===== is_instance_admin (decisión de diseño 3, rediseño Tenant/Role/User) =====


@pytest.mark.asyncio
async def test_set_instance_admin_grants_and_revokes(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")

        granted = await store.set_instance_admin(tenant.id, user.id, True)
        assert granted.is_instance_admin is True

        revoked = await store.set_instance_admin(tenant.id, user.id, False)
        assert revoked.is_instance_admin is False


@pytest.mark.asyncio
async def test_set_instance_admin_rejects_removing_last_one(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        default_admin = (await store.list_users(DEFAULT_TENANT_ID))[0]
        assert default_admin.is_instance_admin is True
        with pytest.raises(InstanceAdminRequiredError):
            await store.set_instance_admin(DEFAULT_TENANT_ID, default_admin.id, False)


@pytest.mark.asyncio
async def test_set_instance_admin_allows_removing_when_another_remains(tmp_path) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        default_admin = (await store.list_users(DEFAULT_TENANT_ID))[0]
        tenant = await store.create_tenant("Acme Corp")
        second = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        await store.set_instance_admin(tenant.id, second.id, True)

        revoked = await store.set_instance_admin(DEFAULT_TENANT_ID, default_admin.id, False)  # no debe lanzar
    assert revoked.is_instance_admin is False


# ===== Migración de bases de datos preexistentes =====


@pytest.mark.asyncio
async def test_migration_backfills_users_without_role_to_admin_role(tmp_path) -> None:
    """Simula una base `auth.db` creada antes de la revisión 9 (sin `role_id`/
    `must_change_password` en `users`, sin tablas `roles`/`role_projects`), abierta
    de nuevo tras la migración: el usuario preexistente debe quedar con acceso
    admin (nunca reducido), no huérfano.
    """
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
        now = datetime.now(UTC).isoformat()
        conn.execute("INSERT INTO tenants (id, name, created_at) VALUES ('acme-corp', 'Acme Corp', ?)", (now,))
        conn.execute(
            "INSERT INTO users (id, tenant_id, username, password_hash, password_salt, created_at) VALUES (?, 'acme-corp', 'alice', 'x', 'y', ?)",
            (str(uuid4()), now),
        )
        conn.commit()
    finally:
        conn.close()

    async with AuthStore(db_path) as store:
        users = await store.list_users("acme-corp")
        assert len(users) == 1
        assert users[0].role_id is not None
        assert users[0].is_blocked is False
        # No hay ningún admin del tenant por defecto que promocionar (esta base no
        # lo tenía todavía) -- el fallback de `_backfill_instance_admins` promociona
        # al usuario más antiguo de toda la instalación, para no migrar nunca a un
        # estado sin ningún is_instance_admin.
        assert users[0].is_instance_admin is True

        role = await store.get_role(users[0].role_id)
        assert role.is_admin is True


@pytest.mark.asyncio
async def test_migration_deduplicates_role_names_across_former_tenants(tmp_path) -> None:
    """Simula una base `auth.db` de la revisión 9 (roles con `tenant_id`, `name`
    único solo por tenant) con dos tenants que tenían un rol "Lector" cada uno --
    tras la migración a `Role` global, `name` es único en toda la instalación, así
    que uno de los dos debe quedar desambiguado, sin perder ningún dato."""
    from uuid import uuid4

    db_path = tmp_path / "auth.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE roles (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, name TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, UNIQUE(tenant_id, name COLLATE NOCASE)
            );
            CREATE TABLE users (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, username TEXT NOT NULL,
                password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, role_id TEXT, created_at TEXT NOT NULL
            );
            """
        )
        now = datetime.now(UTC).isoformat()
        role_a_id, role_b_id = str(uuid4()), str(uuid4())
        conn.execute("INSERT INTO tenants (id, name, created_at) VALUES ('acme-corp', 'Acme Corp', ?)", (now,))
        conn.execute("INSERT INTO tenants (id, name, created_at) VALUES ('globex', 'Globex', ?)", (now,))
        conn.execute("INSERT INTO roles (id, tenant_id, name, is_admin, created_at) VALUES (?, 'acme-corp', 'Lector', 0, ?)", (role_a_id, now))
        conn.execute("INSERT INTO roles (id, tenant_id, name, is_admin, created_at) VALUES (?, 'globex', 'Lector', 0, ?)", (role_b_id, now))
        conn.commit()
    finally:
        conn.close()

    async with AuthStore(db_path) as store:
        roles = await store.list_roles()
        role_names = sorted(role.name for role in roles if role.id in (role_a_id, role_b_id))
    assert role_names == ["Lector", "Lector (globex)"]


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

        monkeypatch.setattr(store._tenant_store, "tenant_exists", _lying_tenant_exists)

        with pytest.raises(TenantAlreadyExistsError):
            await store.create_tenant("Acme Corp")


@pytest.mark.asyncio
async def test_create_role_race_condition_raises_clean_error_not_raw_integrity_error(tmp_path, monkeypatch) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        await store.create_role("Lector")

        async def _lying_role_name_taken(_name: str, *, exclude_role_id=None) -> bool:
            return False

        monkeypatch.setattr(store._role_store, "_role_name_taken", _lying_role_name_taken)

        with pytest.raises(RoleAlreadyExistsError):
            await store.create_role("Lector")


@pytest.mark.asyncio
async def test_create_user_race_condition_raises_clean_error_not_raw_integrity_error(tmp_path, monkeypatch) -> None:
    async with AuthStore(tmp_path / "auth.db") as store:
        tenant = await store.create_tenant("Acme Corp")
        await store.create_user(tenant.id, "alice", "s3cr3t-password")

        async def _lying_username_taken(_tenant_id: str, _username: str) -> bool:
            return False

        monkeypatch.setattr(store._user_store, "_username_taken", _lying_username_taken)

        with pytest.raises(UserAlreadyExistsError):
            await store.create_user(tenant.id, "alice", "otra-password")
