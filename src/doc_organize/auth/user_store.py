"""
Usuarios de autenticación, separados de `AuthStore` (`/tech-debt`, sesión 2026-09-17) --
ver `auth/auth_store.py` (fachada que delega aquí) para el contexto completo de la
separación en `TenantStore`/`RoleStore`/`UserStore`/`SessionStore`.

Comparte la conexión SQLite de `AuthStore` con el resto de stores -- ver el porqué en
la docstring de `tenant_store.py`. Además, `UserStore` sí depende de `TenantStore`/
`RoleStore` (inyectados en el constructor) para validar `tenant_id`/`role_id` antes de
escribir en `users` -- una dependencia genuina (un usuario no puede existir sin un
tenant/rol real), no un atajo de conveniencia: siempre a través de su API pública
(`tenant_exists`, `get_role`, `get_or_create_admin_role_id`), nunca leyendo sus tablas
directamente.

Excepción deliberada: `_count_other_admins`/`_count_other_active_admins` sí hacen un
JOIN directo `users`+`roles` en vez de pedirle el dato a `RoleStore` -- son las guardas
de "último admin" de `update_user`/`delete_user`/`set_user_blocked`, en el camino de
cualquier gestión de usuarios; descomponerlas en "pedir el rol a RoleStore" + "filtrar
en Python" cambiaría 1 consulta por N+1. SQLite no exige que una consulta use "la"
conexión de cada tabla que toca (mismo criterio que `SessionStore.get_session_with_access`,
ver su docstring) -- y ahora todos los stores comparten la misma conexión de todos modos.
"""

import asyncio
import logging
import sqlite3

from uuid import uuid4

import aiosqlite

from doc_organize.core.constants import USERNAME_MAX_LENGTH, USERNAME_PATTERN
from doc_organize.core.exceptions import (
    AuthError,
    InstanceAdminRequiredError,
    RoleInUseError,
    TenantNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from doc_organize.core.models import User

from ._security import hash_password, now_iso, verify_password
from .role_store import RoleStore
from .tenant_store import TenantStore


def _user_from_row(row: sqlite3.Row) -> User:
    """Construye un `User` a partir de una fila con el orden de columnas común a
    `list_users`/`get_user`/`users_for_role` (evita repetir el mismo `User(...)`
    de 8 campos en cada uno)."""
    user_id, tenant_id, username, role_id, must_change_password, is_blocked, is_instance_admin, created_at = row
    return User(
        id=user_id,
        tenant_id=tenant_id,
        username=username,
        role_id=role_id,
        must_change_password=bool(must_change_password),
        is_blocked=bool(is_blocked),
        is_instance_admin=bool(is_instance_admin),
        created_at=created_at,
    )


class UserStore:
    """CRUD de usuarios + autenticación (hash de contraseña, sesión no incluida -- ver `SessionStore`).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        *,
        logger: logging.Logger,
        tenant_store: TenantStore,
        role_store: RoleStore,
    ) -> None:
        self._connection = connection
        self.logger = logger
        self._tenants = tenant_store
        self._roles = role_store

    async def _username_taken(self, tenant_id: str, username: str) -> bool:
        cursor = await self._connection.execute("SELECT 1 FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE", (tenant_id, username))
        return await cursor.fetchone() is not None

    async def _insert_user_row(self, user: User, password_hash: str, salt: str) -> None:
        await self._connection.execute(
            "INSERT INTO users (id, tenant_id, username, password_hash, password_salt, role_id, must_change_password, "
            "is_blocked, is_instance_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user.id,
                user.tenant_id,
                user.username,
                password_hash,
                salt,
                user.role_id,
                int(user.must_change_password),
                int(user.is_blocked),
                int(user.is_instance_admin),
                user.created_at,
            ),
        )

    async def count_users(self, tenant_id: str) -> int:
        """Usuarios de `tenant_id` (cualquier rol) -- usado por `TenantStore.delete_tenant()`
        (vía `AuthStore.delete_tenant()`) para su guarda de "tenant sin usuarios"."""
        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE tenant_id = ?", (tenant_id,))
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (count,) = count_row
        return int(count)

    async def count_users_with_role(self, role_id: str) -> int:
        """Usuarios (de cualquier tenant) con `role_id` asignado -- usado por
        `RoleStore.delete_role()` (vía `AuthStore.delete_role()`) para su guarda de
        "rol en uso"."""
        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE role_id = ?", (role_id,))
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (count,) = count_row
        return int(count)

    async def create_user(self, tenant_id: str, username: str, password: str, role_id: str | None = None, must_change_password: bool = False) -> User:
        """Crea un usuario dentro de `tenant_id`; `username` es único por tenant (case-insensitive).

        Args:
            role_id: Rol a asignar. Si se omite, se usa el rol admin global
                (siempre existe: lo crea el bootstrap del tenant por defecto o
                `RoleStore.get_or_create_admin_role_id()`) — preserva el
                comportamiento previo, donde todo usuario nuevo sin rol explícito
                gestionaba todos los proyectos de su tenant por igual.
            must_change_password: Si `True`, el usuario debe cambiar su contraseña
                en el primer login (`AuthMiddleware`). `False` por defecto para
                usuarios creados explícitamente por un admin con una contraseña
                elegida por ellos mismos.

        Raises:
            AuthError: Si `username`/`password` no cumplen las reglas mínimas.
            TenantNotFoundError: Si `tenant_id` no existe.
            RoleNotFoundError: Si `role_id` no existe.
            UserAlreadyExistsError: Si ya existe ese `username` en el tenant.
        """
        stripped_username = username.strip()
        if not stripped_username:
            raise AuthError("El nombre de usuario no puede estar vacío.")
        if len(stripped_username) > USERNAME_MAX_LENGTH:
            raise AuthError(f"El nombre de usuario no puede superar los {USERNAME_MAX_LENGTH} caracteres.")
        if not USERNAME_PATTERN.match(stripped_username):
            raise AuthError("El nombre de usuario solo puede contener letras, números, puntos, guiones y guion bajo.")
        if not password:
            raise AuthError("La contraseña no puede estar vacía.")

        if not await self._tenants.tenant_exists(tenant_id):
            raise TenantNotFoundError(tenant_id)

        if role_id is None:
            role_id = await self._roles.get_or_create_admin_role_id()
        else:
            await self._roles.get_role(role_id)  # RoleNotFoundError si no existe

        if await self._username_taken(tenant_id, stripped_username):
            raise UserAlreadyExistsError(stripped_username, tenant_id)

        salt, password_hash = await asyncio.to_thread(hash_password, password)
        user = User(
            id=str(uuid4()),
            tenant_id=tenant_id,
            username=stripped_username,
            role_id=role_id,
            must_change_password=must_change_password,
            created_at=now_iso(),
        )
        try:
            await self._insert_user_row(user, password_hash, salt)
            await self._connection.commit()
        except aiosqlite.IntegrityError as exc:
            # Misma ventana de carrera que `TenantStore.create_tenant`/`RoleStore.create_role`:
            # el SELECT de arriba no es la única defensa, el UNIQUE(tenant_id, username) del
            # esquema lo es.
            await self._connection.rollback()
            raise UserAlreadyExistsError(stripped_username, tenant_id) from exc
        self.logger.info(f"Usuario creado: '{user.username}' en tenant '{tenant_id}'")
        return user

    async def list_users(self, tenant_id: str) -> list[User]:
        """Lista los usuarios de `tenant_id`, ordenados por fecha de creación."""
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, role_id, must_change_password, is_blocked, is_instance_admin, created_at "
            "FROM users WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,),
        )
        return [_user_from_row(row) for row in await cursor.fetchall()]

    async def get_user(self, tenant_id: str, user_id: str) -> User:
        """Devuelve el usuario `user_id` de `tenant_id`.

        Raises:
            UserNotFoundError: Si no existe, o pertenece a otro tenant.
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, role_id, must_change_password, is_blocked, is_instance_admin, created_at "
            "FROM users WHERE id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise UserNotFoundError(user_id, tenant_id)
        return _user_from_row(row)

    async def users_for_role(self, role_id: str) -> list[User]:
        """Usuarios (de cualquier tenant) que tienen asignado `role_id`.

        Usada por la página `/admin/roles` para mostrar el alcance real de un rol
        antes de editarlo (mitigación de la ambigüedad de un rol global compartido
        entre tenants, ver AUDIT_PLAN Nivel 3 punto 7) — el llamador filtra por
        tenant si quien pregunta no es `is_instance_admin`.
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, role_id, must_change_password, is_blocked, is_instance_admin, created_at "
            "FROM users WHERE role_id = ? ORDER BY tenant_id, username COLLATE NOCASE",
            (role_id,),
        )
        return [_user_from_row(row) for row in await cursor.fetchall()]

    async def _count_other_admins(self, tenant_id: str, exclude_user_id: str) -> int:
        cursor = await self._connection.execute(
            "SELECT COUNT(*) FROM users u JOIN roles r ON u.role_id = r.id WHERE u.tenant_id = ? AND r.is_admin = 1 AND u.id != ?",
            (tenant_id, exclude_user_id),
        )
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (count,) = count_row
        return int(count)

    async def _count_other_active_admins(self, tenant_id: str, exclude_user_id: str) -> int:
        """Como `_count_other_admins`, pero sin contar usuarios ya bloqueados —
        usada por `set_user_blocked` (un admin bloqueado no cuenta como forma
        utilizable de administrar el tenant)."""
        cursor = await self._connection.execute(
            "SELECT COUNT(*) FROM users u JOIN roles r ON u.role_id = r.id "
            "WHERE u.tenant_id = ? AND r.is_admin = 1 AND u.id != ? AND u.is_blocked = 0",
            (tenant_id, exclude_user_id),
        )
        count_row = await cursor.fetchone()
        assert count_row is not None
        (count,) = count_row
        return int(count)

    async def _count_other_users(self, tenant_id: str, exclude_user_id: str) -> int:
        """Usuarios de `tenant_id` distintos de `exclude_user_id` (cualquier rol) —
        usada para relajar las guardas de "último admin" cuando ese admin es en
        realidad el ÚLTIMO usuario del tenant sin más (nadie queda desatendido:
        vaciar el tenant del todo es un estado terminal legítimo, camino hacia
        `delete_tenant`, no un tenant vivo sin quien lo administre)."""
        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE tenant_id = ? AND id != ?", (tenant_id, exclude_user_id))
        count_row = await cursor.fetchone()
        assert count_row is not None
        (count,) = count_row
        return int(count)

    async def update_user(self, tenant_id: str, user_id: str, *, role_id: str | None = None, password: str | None = None) -> User:
        """Actualiza el rol y/o restablece la contraseña de un usuario (uso admin).

        Restablecer `password` fija `must_change_password=True` — el usuario debe
        elegir una nueva contraseña en su próximo login, igual que el admin de
        bootstrap.

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleNotFoundError: Si `role_id` no existe.
            RoleInUseError: Si el cambio de rol dejaría a OTROS usuarios del
                tenant sin ningún admin (no se aplica si `user_id` es el único
                usuario del tenant: vaciarlo de admins por completo es un estado
                terminal legítimo, no deja a nadie desatendido).
            AuthError: Si `password` se pasa vacía.
        """
        current = await self.get_user(tenant_id, user_id)

        new_role_id = current.role_id
        if role_id is not None and role_id != current.role_id:
            old_role = await self._roles.get_role(current.role_id)
            new_role = await self._roles.get_role(role_id)
            if (
                old_role.is_admin
                and not new_role.is_admin
                and await self._count_other_admins(tenant_id, user_id) == 0
                and await self._count_other_users(tenant_id, user_id) > 0
            ):
                raise RoleInUseError("No se puede quitar el rol admin al último usuario admin del tenant.")
            new_role_id = role_id

        if new_role_id != current.role_id:
            await self._connection.execute("UPDATE users SET role_id = ? WHERE id = ?", (new_role_id, user_id))

        must_change_password = current.must_change_password
        if password is not None:
            if not password:
                raise AuthError("La contraseña no puede estar vacía.")
            new_salt, new_hash = await asyncio.to_thread(hash_password, password)
            must_change_password = True
            await self._connection.execute(
                "UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = ? WHERE id = ?",
                (new_hash, new_salt, int(must_change_password), user_id),
            )

        await self._connection.commit()
        return User(
            id=user_id,
            tenant_id=tenant_id,
            username=current.username,
            role_id=new_role_id,
            must_change_password=must_change_password,
            is_blocked=current.is_blocked,
            is_instance_admin=current.is_instance_admin,
            created_at=current.created_at,
        )

    async def set_user_blocked(self, tenant_id: str, user_id: str, blocked: bool) -> User:
        """Bloquea/desbloquea un usuario.

        Al bloquear (`blocked=True`), borra TODAS las sesiones activas de
        `user_id` en la MISMA transacción que fija `is_blocked=1` — no basta con
        impedir logins futuros (`authenticate()` ya rechaza usuarios bloqueados),
        una sesión ya abierta debía invalidarse de inmediato, no esperar a que
        expire sola (hasta `SESSION_LIFETIME_HOURS`, 24h).

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleInUseError: Si bloquear dejaría a OTROS usuarios del tenant sin
                ningún admin activo (mismo criterio que `delete_user`/`update_user`:
                no se aplica si `user_id` es el único usuario del tenant).
        """
        current = await self.get_user(tenant_id, user_id)
        if blocked and not current.is_blocked:
            role = await self._roles.get_role(current.role_id)
            if (
                role.is_admin
                and await self._count_other_active_admins(tenant_id, user_id) == 0
                and await self._count_other_users(tenant_id, user_id) > 0
            ):
                raise RoleInUseError("No se puede bloquear al último usuario admin activo del tenant.")

        await self._connection.execute("UPDATE users SET is_blocked = ? WHERE id = ?", (int(blocked), user_id))
        if blocked:
            await self._connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await self._connection.commit()
        return User(
            id=user_id,
            tenant_id=tenant_id,
            username=current.username,
            role_id=current.role_id,
            must_change_password=current.must_change_password,
            is_blocked=blocked,
            is_instance_admin=current.is_instance_admin,
            created_at=current.created_at,
        )

    async def set_instance_admin(self, tenant_id: str, user_id: str, value: bool) -> User:
        """Concede/retira `is_instance_admin` a un usuario de cualquier tenant.

        La autorización de quién puede llamar a esto (solo otro `is_instance_admin`)
        vive en la capa de rutas (`require_instance_admin`), no aquí.

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            InstanceAdminRequiredError: Si retirarlo dejaría la instalación entera
                sin NINGÚN `is_instance_admin` (guarda global, no por tenant).
        """
        current = await self.get_user(tenant_id, user_id)
        if not value and current.is_instance_admin:
            cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE is_instance_admin = 1 AND id != ?", (user_id,))
            count_row = await cursor.fetchone()
            assert count_row is not None
            (remaining,) = count_row
            if remaining == 0:
                raise InstanceAdminRequiredError("No se puede quitar is_instance_admin al último usuario con ese nivel.")

        await self._connection.execute("UPDATE users SET is_instance_admin = ? WHERE id = ?", (int(value), user_id))
        await self._connection.commit()
        return User(
            id=user_id,
            tenant_id=tenant_id,
            username=current.username,
            role_id=current.role_id,
            must_change_password=current.must_change_password,
            is_blocked=current.is_blocked,
            is_instance_admin=value,
            created_at=current.created_at,
        )

    async def delete_user(self, tenant_id: str, user_id: str) -> None:
        """Elimina un usuario (sus sesiones se borran en cascada vía FK).

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleInUseError: Si es el último admin del tenant y quedarían OTROS
                usuarios sin ninguno (no se aplica si es el único usuario del
                tenant: vaciarlo del todo es un estado terminal legítimo, camino
                hacia `delete_tenant`, que sí exige cero usuarios).
        """
        user = await self.get_user(tenant_id, user_id)
        role = await self._roles.get_role(user.role_id)
        if role.is_admin and await self._count_other_admins(tenant_id, user_id) == 0 and await self._count_other_users(tenant_id, user_id) > 0:
            raise RoleInUseError("No se puede eliminar el último usuario admin del tenant.")

        await self._connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await self._connection.commit()

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """Cambio de contraseña autoservicio. `True` si tuvo éxito, `False` si `current_password` no coincide.

        Verifica `current_password` antes de aplicar el cambio (una sesión
        comprometida no puede cambiar la contraseña sin conocer la actual). Limpia
        `must_change_password` incondicionalmente al terminar con éxito.

        Raises:
            AuthError: Si `new_password` está vacía.
        """
        cursor = await self._connection.execute("SELECT password_hash, password_salt FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if row is None:
            return False
        password_hash, salt = row
        if not await asyncio.to_thread(verify_password, current_password, salt, password_hash):
            return False
        if not new_password:
            raise AuthError("La nueva contraseña no puede estar vacía.")

        new_salt, new_hash = await asyncio.to_thread(hash_password, new_password)
        await self._connection.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 0 WHERE id = ?",
            (new_hash, new_salt, user_id),
        )
        await self._connection.commit()
        return True

    async def authenticate(self, tenant_id: str, username: str, password: str) -> User | None:
        """Valida credenciales; `None` si el tenant/usuario no existe, la contraseña
        no coincide, o el usuario está bloqueado.

        Deliberadamente devuelve el mismo `None` en los tres casos para no revelar
        si una cuenta existe o está bloqueada (mitigación estándar de enumeración
        de usuarios). La verificación de contraseña (`_verify_password`, coste fijo
        de `scrypt`) se ejecuta siempre, incluso para un usuario ya bloqueado —
        devolver `None` antes de verificarla introduciría una diferencia de tiempo
        que permitiría distinguir "bloqueado" de "contraseña incorrecta".
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, password_hash, password_salt, role_id, must_change_password, "
            "is_blocked, is_instance_admin, created_at "
            "FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE",
            (tenant_id, username.strip()),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        (
            user_id,
            row_tenant_id,
            row_username,
            password_hash,
            salt,
            role_id,
            must_change_password,
            is_blocked,
            is_instance_admin,
            created_at,
        ) = row
        is_valid = await asyncio.to_thread(verify_password, password, salt, password_hash)
        if not is_valid or is_blocked:
            return None

        return User(
            id=user_id,
            tenant_id=row_tenant_id,
            username=row_username,
            role_id=role_id,
            must_change_password=bool(must_change_password),
            is_blocked=bool(is_blocked),
            is_instance_admin=bool(is_instance_admin),
            created_at=created_at,
        )


__all__ = ["UserStore"]
