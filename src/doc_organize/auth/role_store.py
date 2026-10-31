"""
Roles de autenticación, separados de `AuthStore` (`/tech-debt`, sesión 2026-09-17) --
ver `auth/auth_store.py` (fachada que delega aquí) para el contexto completo de la
separación en `TenantStore`/`RoleStore`/`UserStore`/`SessionStore`.

Comparte la conexión SQLite de `AuthStore` con el resto de stores -- ver el porqué en
la docstring de `tenant_store.py`. `RoleStore` no depende de `UserStore` -- los conteos
de usuarios que necesitan `delete_role`/`update_role` (guardas de "último rol admin"/
"rol en uso") los resuelve `AuthStore` vía `UserStore` y se los pasa ya calculados, para
no acoplar los dos stores solo por una guarda ocasional (no es un camino caliente, a
diferencia del JOIN de `get_session_with_access`/`_count_other_admins`, que sí se
mantienen como consultas cruzadas directas -- ver sus docstrings en
`session_store.py`/`user_store.py`).
"""

import logging

from uuid import uuid4

import aiosqlite

from doc_organize.core.constants import DEFAULT_ADMIN_ROLE_NAME, ROLE_NAME_MAX_LENGTH, ROLE_NAME_PATTERN
from doc_organize.core.exceptions import AuthError, RoleAlreadyExistsError, RoleInUseError, RoleNotFoundError
from doc_organize.core.models import Role

from ._security import now_iso


def _validate_role_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise AuthError("El nombre del rol no puede estar vacío.")
    if len(stripped) > ROLE_NAME_MAX_LENGTH:
        raise AuthError(f"El nombre del rol no puede superar los {ROLE_NAME_MAX_LENGTH} caracteres.")
    if not ROLE_NAME_PATTERN.match(stripped):
        raise AuthError("El nombre del rol solo puede contener letras, números, espacios, puntos, guiones y guion bajo.")
    return stripped


class RoleStore:
    """CRUD de roles globales (rediseño Tenant/Role/User: sin `tenant_id`).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self, connection: aiosqlite.Connection, *, logger: logging.Logger) -> None:
        self._connection = connection
        self.logger = logger

    async def _role_name_taken(self, name: str, *, exclude_role_id: str | None = None) -> bool:
        if exclude_role_id is None:
            cursor = await self._connection.execute("SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE", (name,))
        else:
            cursor = await self._connection.execute(
                "SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE AND id != ?",
                (name, exclude_role_id),
            )
        return await cursor.fetchone() is not None

    async def _insert_role_row(self, role: Role) -> None:
        await self._connection.execute(
            "INSERT INTO roles (id, name, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (role.id, role.name, int(role.is_admin), role.created_at),
        )
        if role.project_names:
            await self._connection.executemany(
                "INSERT INTO role_projects (role_id, project_name) VALUES (?, ?)",
                [(role.id, project_name) for project_name in role.project_names],
            )

    async def _replace_role_associations(self, role_id: str, project_names: list[str]) -> None:
        """Reemplaza por completo `role_projects` de `role_id` (usado por
        `update_role`, sin commit — el llamador decide la transaccion)."""
        await self._connection.execute("DELETE FROM role_projects WHERE role_id = ?", (role_id,))
        if project_names:
            await self._connection.executemany(
                "INSERT INTO role_projects (role_id, project_name) VALUES (?, ?)",
                [(role_id, project_name) for project_name in project_names],
            )

    async def _load_role_project_names(self, role_id: str) -> list[str]:
        cursor = await self._connection.execute("SELECT project_name FROM role_projects WHERE role_id = ? ORDER BY project_name", (role_id,))
        return [row[0] for row in await cursor.fetchall()]

    async def get_or_create_admin_role_id(self) -> str:
        """Devuelve el `id` del primer rol `is_admin`, creándolo si no existe todavía.

        Público (a diferencia del resto de helpers `_`-privados de este módulo):
        lo usa tanto `AuthStore` (bootstrap de `DEFAULT_TENANT_ID`) como `UserStore`
        (`create_user` sin `role_id` explícito) -- ambos fuera de `RoleStore`.
        """
        cursor = await self._connection.execute("SELECT id FROM roles WHERE is_admin = 1 ORDER BY created_at LIMIT 1")
        row = await cursor.fetchone()
        if row is not None:
            return str(row[0])

        role = Role(id=str(uuid4()), name=DEFAULT_ADMIN_ROLE_NAME, is_admin=True, created_at=now_iso())
        await self._insert_role_row(role)
        return role.id

    async def create_role(self, name: str, is_admin: bool = False, project_names: list[str] | None = None) -> Role:
        """Crea un rol; `name` es único globalmente (case-insensitive).

        Args:
            project_names: Proyectos a los que da acceso este rol (interpretados
                siempre dentro del tenant del usuario que lo tenga asignado — el
                rol en sí no fija ningún tenant). Vacío por defecto.

        Raises:
            AuthError: Si `name` no cumple las reglas mínimas, o si `is_admin=True`
                se combina con una lista de proyectos no vacía (un rol admin ve
                todos los proyectos del tenant de su usuario; una lista explícita
                sería ambigua).
            RoleAlreadyExistsError: Si ya existe ese `name`.
        """
        stripped_name = _validate_role_name(name)
        deduped_projects = list(dict.fromkeys(project_names or []))
        if is_admin and deduped_projects:
            raise AuthError("Un rol admin ve todos los proyectos del tenant; no se le puede asignar una lista de proyectos.")

        if await self._role_name_taken(stripped_name):
            raise RoleAlreadyExistsError(stripped_name)

        role = Role(id=str(uuid4()), name=stripped_name, is_admin=is_admin, project_names=deduped_projects, created_at=now_iso())
        try:
            await self._insert_role_row(role)
            await self._connection.commit()
        except aiosqlite.IntegrityError as exc:
            # Misma ventana de carrera que `TenantStore.create_tenant`: el SELECT de
            # arriba no es la única defensa, el UNIQUE(name) del esquema lo es.
            await self._connection.rollback()
            raise RoleAlreadyExistsError(stripped_name) from exc
        self.logger.info(f"Rol creado: '{role.name}' (is_admin={is_admin})")
        return role

    async def list_roles(self) -> list[Role]:
        """Lista todos los roles, ordenados por fecha de creación."""
        cursor = await self._connection.execute("SELECT id, name, is_admin, created_at FROM roles ORDER BY created_at")
        rows = await cursor.fetchall()
        roles = []
        for row in rows:
            project_names = await self._load_role_project_names(row[0])
            roles.append(Role(id=row[0], name=row[1], is_admin=bool(row[2]), project_names=project_names, created_at=row[3]))
        return roles

    async def get_role(self, role_id: str) -> Role:
        """Devuelve el rol `role_id`.

        Raises:
            RoleNotFoundError: Si no existe.
        """
        cursor = await self._connection.execute("SELECT id, name, is_admin, created_at FROM roles WHERE id = ?", (role_id,))
        row = await cursor.fetchone()
        if row is None:
            raise RoleNotFoundError(role_id)
        project_names = await self._load_role_project_names(row[0])
        return Role(id=row[0], name=row[1], is_admin=bool(row[2]), project_names=project_names, created_at=row[3])

    @staticmethod
    def _resolve_role_update(
        current: Role,
        *,
        name: str | None,
        is_admin: bool | None,
        project_names: list[str] | None,
    ) -> tuple[str, bool, list[str]]:
        """Calcula name/is_admin/project_names nuevos para `update_role` a partir de
        `current` y los campos pasados (solo los no-`None` cambian), validando las
        combinaciones prohibidas. No toca la base de datos.

        Raises:
            AuthError: Ver `update_role`.
        """
        if is_admin is False and current.is_admin and project_names is None:
            raise AuthError(
                "Al quitar is_admin a un rol, hay que indicar explícitamente project_names "
                "(puede ser una lista vacía) — de lo contrario el rol quedaría sin acceso a ningún "
                "proyecto sin que se haya pedido explícitamente."
            )

        new_name = current.name if name is None else _validate_role_name(name)
        new_is_admin = current.is_admin if is_admin is None else is_admin
        new_project_names = current.project_names if project_names is None else list(dict.fromkeys(project_names))

        if new_is_admin and new_project_names:
            raise AuthError("Un rol admin ve todos los proyectos del tenant; no se le puede asignar una lista de proyectos.")

        return new_name, new_is_admin, new_project_names

    async def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        is_admin: bool | None = None,
        project_names: list[str] | None = None,
    ) -> Role:
        """Actualiza nombre/`is_admin`/proyectos de un rol. Solo los campos pasados
        cambian. `project_names`, si se pasa, reemplaza la lista completa.

        Raises:
            AuthError: Si `is_admin` pasa explícitamente de `True` a `False` sin
                pasar `project_names` en la misma llamada (ver docstring de
                `_resolve_role_update`).
            RoleNotFoundError: Si `role_id` no existe.
            RoleAlreadyExistsError: Si `name` ya lo usa otro rol.
        """
        current = await self.get_role(role_id)
        new_name, new_is_admin, new_project_names = self._resolve_role_update(current, name=name, is_admin=is_admin, project_names=project_names)

        if new_name.lower() != current.name.lower() and await self._role_name_taken(new_name, exclude_role_id=role_id):
            raise RoleAlreadyExistsError(new_name)

        await self._connection.execute("UPDATE roles SET name = ?, is_admin = ? WHERE id = ?", (new_name, int(new_is_admin), role_id))
        await self._replace_role_associations(role_id, new_project_names)
        await self._connection.commit()
        return Role(id=role_id, name=new_name, is_admin=new_is_admin, project_names=new_project_names, created_at=current.created_at)

    async def delete_role(self, role_id: str, *, user_count: int) -> None:
        """Elimina un rol.

        Args:
            user_count: Número de usuarios (de cualquier tenant) que tienen este
                rol asignado -- lo calcula `AuthStore.delete_role()` vía
                `UserStore.count_users_with_role()`; `RoleStore` no consulta la
                tabla `users` directamente (no es un camino caliente, ver
                docstring del módulo).

        Raises:
            RoleNotFoundError: Si no existe.
            RoleInUseError: Si `user_count > 0`, o si es el último rol `is_admin`
                de todo el sistema (evita dejar la instalación entera sin ninguna
                forma de gestionar ningún tenant — la guarda ya no es por tenant,
                porque el rol tampoco lo es).
        """
        role = await self.get_role(role_id)

        if user_count > 0:
            raise RoleInUseError(f"El rol '{role.name}' está asignado a {user_count} usuario(s); reasígnalos antes de eliminarlo.")

        if role.is_admin:
            cursor = await self._connection.execute("SELECT COUNT(*) FROM roles WHERE is_admin = 1 AND id != ?", (role_id,))
            count_row = await cursor.fetchone()
            assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
            (other_admin_roles,) = count_row
            if other_admin_roles == 0:
                raise RoleInUseError("No se puede eliminar el último rol admin del sistema.")

        await self._connection.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        await self._connection.commit()

    async def can_access_project(self, role_id: str, project_name: str) -> bool:
        """`True` si el rol `role_id` puede acceder a `project_name`.

        Un rol `is_admin` accede a cualquier proyecto del tenant de su usuario sin
        estar listado en `role_projects`. Comparación de nombre case-insensitive
        (mismo criterio que `ProjectRegistry.get_project()`). La pertenencia real
        del proyecto a un tenant concreto la resuelve el llamador (`ProjectRegistry`,
        con el `tenant_id` de la sesión) — este método no conoce tenants.
        """
        cursor = await self._connection.execute("SELECT is_admin FROM roles WHERE id = ?", (role_id,))
        row = await cursor.fetchone()
        if row is None:
            return False
        if bool(row[0]):
            return True
        cursor = await self._connection.execute(
            "SELECT 1 FROM role_projects WHERE role_id = ? AND project_name = ? COLLATE NOCASE",
            (role_id, project_name),
        )
        return await cursor.fetchone() is not None


__all__ = ["RoleStore"]
