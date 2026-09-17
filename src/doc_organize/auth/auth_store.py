"""
Almacen de tenants, roles, usuarios y sesiones (SQLite + WAL) para autenticacion
multi-usuario, multi-tenant y control de acceso por rol (revision 8 §2.7.2,
revision 9 roles y gestion de usuarios, rediseno Tenant/Role/User).

`AuthStore` es una fachada fina: delega en `TenantStore`/`RoleStore`/`UserStore`/
`SessionStore` (cada uno con su propia conexión SQLite), separados de aquí por
deuda técnica (`/tech-debt`, sesión 2026-09-17) -- antes una única clase de ~1050
líneas mezclaba las 4 responsabilidades. La API pública de `AuthStore` no cambia:
cualquier código que ya la use (rutas web, CLI, tests) sigue funcionando igual.
"""

import asyncio

from pathlib import Path
from typing import Self
from uuid import uuid4

import aiosqlite

from doc_organize.auth.migrations import apply_pending_migrations
from doc_organize.auth.role_store import RoleStore
from doc_organize.auth.session_store import AuthenticatedSession, SessionStore
from doc_organize.auth.tenant_store import TenantStore
from doc_organize.auth.user_store import UserStore
from doc_organize.core.constants import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, DEFAULT_TENANT_ID
from doc_organize.core.exceptions import AuthError
from doc_organize.core.models import Role, Session, Tenant, User
from doc_organize.utils.logging import get_logger

from ._security import hash_password, now_iso

_DEFAULT_AUTH_DB_PATH = Path.home() / ".doc_organize" / "auth.db"
_NOT_OPEN_ERROR = "AuthStore debe usarse como context manager async ('async with')."

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(name COLLATE NOCASE)
);
CREATE TABLE IF NOT EXISTS role_projects (
    role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    project_name TEXT NOT NULL,
    PRIMARY KEY (role_id, project_name)
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role_id TEXT REFERENCES roles(id),
    must_change_password INTEGER NOT NULL DEFAULT 0,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    is_instance_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, username COLLATE NOCASE)
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


def is_factory_admin_account(user: User) -> bool:
    """`True` si `user` es la cuenta de fábrica del tenant por defecto
    (`DEFAULT_TENANT_ID`/`DEFAULT_ADMIN_USERNAME`) con la contraseña de fábrica
    todavía sin cambiar.

    Usada por `web/routes/auth.py` para bloquear el login de esta identidad exacta
    en modo no-loopback (decisión de diseño 1 del rediseño Tenant/Role/User): la
    contraseña de fábrica es pública (documentada), así que cualquiera podría
    autenticarse con ella salvo que se impida completar el login mientras siga
    activa — a diferencia de una contraseña reseteada por un admin a un usuario
    cualquiera (`must_change_password=True` también, pero con un valor temporal
    que solo conocen el admin y ese usuario, sin el mismo riesgo).
    """
    return user.tenant_id == DEFAULT_TENANT_ID and user.username == DEFAULT_ADMIN_USERNAME and user.must_change_password


class AuthStore:
    """Almacen de tenants, roles, usuarios y sesiones para autenticacion multi-tenant.

    SQLite+WAL en `~/.doc_organize/auth.db`, no el patron JSON+asyncio.Lock de
    `ProjectRegistry`: a diferencia de `projects.json`, aqui hay relaciones reales
    entre varias entidades (tenant -> usuario -> sesion, rol -> usuario) que se
    benefician de FK real e integridad referencial. Las contrasenas se hashean con
    `hashlib.scrypt` (parametros OWASP) + salt aleatorio por usuario; los tokens de
    sesion son opacos (`secrets.token_urlsafe`), nunca derivados de la contrasena.

    Rediseño Tenant/Role/User: `Role` ya no está ligado a un tenant (`name` único
    globalmente), así que el bootstrap automático de fábrica (tenant + rol admin +
    usuario `admin` con `must_change_password=True`) ya solo ocurre, una vez, para
    `DEFAULT_TENANT_ID` — ver `_ensure_default_tenant_bootstrap()`, llamado desde
    `__aenter__()` igual que las migraciones. `create_tenant()` (para tenants
    adicionales) ya NO aprovisiona usuario/rol: los da de alta un `is_instance_admin`
    o `user create` por CLI, porque no hay "rol admin de ESE tenant" que crear.

    Internamente delega en `TenantStore`/`RoleStore`/`UserStore`/`SessionStore`
    (separados por responsabilidad, `/tech-debt` sesión 2026-09-17), pero los 4
    comparten esta misma conexión SQLite en vez de abrir la suya propia: `AuthStore`
    no es un singleton de vida larga en esta app -- se instancia una vez por
    petición (ver `web/dependencies.py::get_auth_store`), así que 4 conexiones
    independientes multiplicarían por 4 el coste de abrir/cerrar conexión en el
    hot path de cada request autenticada (AUDIT_CODE, misma sesión).

    Attributes:
        db_path (Path): Ruta al archivo SQLite.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     db_path = Path(tempfile.mkdtemp()) / "auth.db"
        ...     async with AuthStore(db_path) as store:
        ...         # DEFAULT_TENANT_ID ya existe de fábrica, con usuario admin.
        ...         tenant = await store.create_tenant("Acme Corp")
        ...         role = await store.create_role("Lector", project_names=["Proyecto A"])
        ...         user = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        ...         return user.username
        >>> asyncio.run(main())
        'alice'
    """

    def __init__(self, db_path: str | Path = _DEFAULT_AUTH_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.logger = get_logger(__name__)
        self._conn: aiosqlite.Connection | None = None
        self._tenants: TenantStore | None = None
        self._roles: RoleStore | None = None
        self._users: UserStore | None = None
        self._sessions: SessionStore | None = None

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self.db_path.parent.mkdir, parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        await apply_pending_migrations(self._conn, logger=self.logger)

        self._tenants = TenantStore(self._conn, logger=self.logger)
        self._roles = RoleStore(self._conn, logger=self.logger)
        self._users = UserStore(self._conn, logger=self.logger, tenant_store=self._tenants, role_store=self._roles)
        self._sessions = SessionStore(self._conn, logger=self.logger)

        await self._ensure_default_tenant_bootstrap()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._tenants = self._roles = self._users = self._sessions = None

    async def _ensure_default_tenant_bootstrap(self) -> None:
        """Garantiza que `DEFAULT_TENANT_ID` existe, con su rol y usuario admin de
        fábrica, sin aprovisionamiento manual previo. Se ejecuta en cada apertura
        de `AuthStore` (CLI y web por igual), idempotente igual que las migraciones.

        Exclusivo de `DEFAULT_TENANT_ID`: `TenantStore.create_tenant()` (para
        cualquier otro tenant) ya no aprovisiona usuario/rol. Si el tenant por
        defecto se borra (`delete_tenant`), esta función lo vuelve a crear de
        fábrica (con un usuario `admin`/contraseña de fábrica nuevo,
        `must_change_password=True`) la siguiente vez que se abra `AuthStore` --
        comportamiento intencional, no un cabo suelto: nunca deja la instalación
        sin ninguna forma de entrar.

        `self._tenants`/`self._roles` ya comparten `self._conn` con este método, así
        que usar su API pública (`tenant_exists`/`get_or_create_admin_role_id`) sigue
        siendo una única transacción -- tenant + rol admin + usuario se confirman
        juntos con el `commit()` de abajo, o ninguno si hay `IntegrityError`. Solo el
        INSERT del usuario se mantiene inline (no vía `UserStore`, que exigiría
        contraseña ya calculada más validaciones que no aplican al usuario de
        fábrica) -- mismo criterio de "duplicar en vez de acoplar" que
        `ConfirmedActionRequest` en `web/routes/`.
        """
        if await self._tenant_store.tenant_exists(DEFAULT_TENANT_ID):
            return

        tenant = Tenant(id=DEFAULT_TENANT_ID, name="Default", created_at=now_iso())
        admin_role_id = await self._role_store.get_or_create_admin_role_id()
        salt, password_hash = await asyncio.to_thread(hash_password, DEFAULT_ADMIN_PASSWORD)
        admin_user = User(
            id=str(uuid4()),
            tenant_id=DEFAULT_TENANT_ID,
            username=DEFAULT_ADMIN_USERNAME,
            role_id=admin_role_id,
            must_change_password=True,
            is_instance_admin=True,
            created_at=tenant.created_at,
        )
        assert self._conn is not None  # ya abierta por __aenter__ antes de llamar aquí
        try:
            await self._conn.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant.id, tenant.name, tenant.created_at),
            )
            await self._conn.execute(
                "INSERT INTO users (id, tenant_id, username, password_hash, password_salt, role_id, must_change_password, "
                "is_blocked, is_instance_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    admin_user.id,
                    admin_user.tenant_id,
                    admin_user.username,
                    password_hash,
                    salt,
                    admin_user.role_id,
                    int(admin_user.must_change_password),
                    int(admin_user.is_blocked),
                    int(admin_user.is_instance_admin),
                    admin_user.created_at,
                ),
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError:
            # Ventana de carrera entre el tenant_exists() de arriba y este INSERT:
            # otra apertura concurrente de AuthStore ya lo creó -- nada que hacer.
            await self._conn.rollback()
            return
        self.logger.info(f"Bootstrap: tenant '{DEFAULT_TENANT_ID}' creado con usuario admin de fábrica ('{DEFAULT_ADMIN_USERNAME}').")

    @property
    def _tenant_store(self) -> TenantStore:
        if self._tenants is None:
            raise AuthError(_NOT_OPEN_ERROR)
        return self._tenants

    @property
    def _role_store(self) -> RoleStore:
        if self._roles is None:
            raise AuthError(_NOT_OPEN_ERROR)
        return self._roles

    @property
    def _user_store(self) -> UserStore:
        if self._users is None:
            raise AuthError(_NOT_OPEN_ERROR)
        return self._users

    @property
    def _session_store(self) -> SessionStore:
        if self._sessions is None:
            raise AuthError(_NOT_OPEN_ERROR)
        return self._sessions

    # ===== Tenants (ver `TenantStore`) =====

    async def create_tenant(self, name: str) -> Tenant:
        """Crea un tenant nuevo; su `id` se deriva de `name` (slug). Ver `TenantStore.create_tenant`.

        Raises:
            AuthError: Si `name` esta vacio o no produce un slug valido.
            TenantAlreadyExistsError: Si ya existe un tenant con ese `id`.
        """
        return await self._tenant_store.create_tenant(name)

    async def tenant_exists(self, tenant_id: str) -> bool:
        """True si hay un tenant registrado con ese `id` exacto."""
        return await self._tenant_store.tenant_exists(tenant_id)

    async def list_tenants(self) -> list[Tenant]:
        """Lista todos los tenants (pantalla cruzada "Tenants y usuarios", solo `is_instance_admin`)."""
        return await self._tenant_store.list_tenants()

    async def delete_tenant(self, tenant_id: str, *, has_projects: bool) -> None:
        """Elimina un tenant. Solo si no tiene usuarios NI proyectos asociados. Ver `TenantStore.delete_tenant`.

        Raises:
            TenantNotFoundError: Si `tenant_id` no existe.
            TenantInUseError: Si tiene usuarios o proyectos asociados.
        """
        user_count = await self._user_store.count_users(tenant_id)
        await self._tenant_store.delete_tenant(tenant_id, has_projects=has_projects, user_count=user_count)

    # ===== Roles (ver `RoleStore`) =====

    async def create_role(self, name: str, is_admin: bool = False, project_names: list[str] | None = None) -> Role:
        """Crea un rol; `name` es único globalmente (case-insensitive). Ver `RoleStore.create_role`.

        Raises:
            AuthError: Si `name` no cumple las reglas mínimas, o si `is_admin=True`
                se combina con una lista de proyectos no vacía.
            RoleAlreadyExistsError: Si ya existe ese `name`.
        """
        return await self._role_store.create_role(name, is_admin=is_admin, project_names=project_names)

    async def list_roles(self) -> list[Role]:
        """Lista todos los roles, ordenados por fecha de creación."""
        return await self._role_store.list_roles()

    async def get_role(self, role_id: str) -> Role:
        """Devuelve el rol `role_id`.

        Raises:
            RoleNotFoundError: Si no existe.
        """
        return await self._role_store.get_role(role_id)

    async def users_for_role(self, role_id: str) -> list[User]:
        """Usuarios (de cualquier tenant) que tienen asignado `role_id`."""
        return await self._user_store.users_for_role(role_id)

    async def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        is_admin: bool | None = None,
        project_names: list[str] | None = None,
    ) -> Role:
        """Actualiza nombre/`is_admin`/proyectos de un rol. Ver `RoleStore.update_role`.

        Raises:
            AuthError: Si `is_admin` pasa explícitamente de `True` a `False` sin
                pasar `project_names` en la misma llamada.
            RoleNotFoundError: Si `role_id` no existe.
            RoleAlreadyExistsError: Si `name` ya lo usa otro rol.
        """
        return await self._role_store.update_role(role_id, name=name, is_admin=is_admin, project_names=project_names)

    async def delete_role(self, role_id: str) -> None:
        """Elimina un rol. Ver `RoleStore.delete_role`.

        Raises:
            RoleNotFoundError: Si no existe.
            RoleInUseError: Si algún usuario lo tiene asignado, o si es el último
                rol `is_admin` de todo el sistema.
        """
        user_count = await self._user_store.count_users_with_role(role_id)
        await self._role_store.delete_role(role_id, user_count=user_count)

    async def can_access_project(self, role_id: str, project_name: str) -> bool:
        """`True` si el rol `role_id` puede acceder a `project_name`."""
        return await self._role_store.can_access_project(role_id, project_name)

    # ===== Usuarios (ver `UserStore`) =====

    async def create_user(self, tenant_id: str, username: str, password: str, role_id: str | None = None, must_change_password: bool = False) -> User:
        """Crea un usuario dentro de `tenant_id`; `username` es único por tenant (case-insensitive).
        Ver `UserStore.create_user`.

        Raises:
            AuthError: Si `username`/`password` no cumplen las reglas mínimas.
            TenantNotFoundError: Si `tenant_id` no existe.
            RoleNotFoundError: Si `role_id` no existe.
            UserAlreadyExistsError: Si ya existe ese `username` en el tenant.
        """
        return await self._user_store.create_user(tenant_id, username, password, role_id=role_id, must_change_password=must_change_password)

    async def list_users(self, tenant_id: str) -> list[User]:
        """Lista los usuarios de `tenant_id`, ordenados por fecha de creación."""
        return await self._user_store.list_users(tenant_id)

    async def get_user(self, tenant_id: str, user_id: str) -> User:
        """Devuelve el usuario `user_id` de `tenant_id`.

        Raises:
            UserNotFoundError: Si no existe, o pertenece a otro tenant.
        """
        return await self._user_store.get_user(tenant_id, user_id)

    async def update_user(self, tenant_id: str, user_id: str, *, role_id: str | None = None, password: str | None = None) -> User:
        """Actualiza el rol y/o restablece la contraseña de un usuario (uso admin).
        Ver `UserStore.update_user`.

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleNotFoundError: Si `role_id` no existe.
            RoleInUseError: Si el cambio de rol dejaría a OTROS usuarios del
                tenant sin ningún admin.
            AuthError: Si `password` se pasa vacía.
        """
        return await self._user_store.update_user(tenant_id, user_id, role_id=role_id, password=password)

    async def set_user_blocked(self, tenant_id: str, user_id: str, blocked: bool) -> User:
        """Bloquea/desbloquea un usuario. Ver `UserStore.set_user_blocked`.

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleInUseError: Si bloquear dejaría a OTROS usuarios del tenant sin
                ningún admin activo.
        """
        return await self._user_store.set_user_blocked(tenant_id, user_id, blocked)

    async def set_instance_admin(self, tenant_id: str, user_id: str, value: bool) -> User:
        """Concede/retira `is_instance_admin` a un usuario de cualquier tenant.

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            InstanceAdminRequiredError: Si retirarlo dejaría la instalación entera
                sin NINGÚN `is_instance_admin`.
        """
        return await self._user_store.set_instance_admin(tenant_id, user_id, value)

    async def delete_user(self, tenant_id: str, user_id: str) -> None:
        """Elimina un usuario (sus sesiones se borran en cascada vía FK).

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleInUseError: Si es el último admin del tenant y quedarían OTROS
                usuarios sin ninguno.
        """
        await self._user_store.delete_user(tenant_id, user_id)

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """Cambio de contraseña autoservicio. `True` si tuvo éxito, `False` si `current_password` no coincide.

        Raises:
            AuthError: Si `new_password` está vacía.
        """
        return await self._user_store.change_password(user_id, current_password, new_password)

    async def authenticate(self, tenant_id: str, username: str, password: str) -> User | None:
        """Valida credenciales; `None` si el tenant/usuario no existe, la contraseña
        no coincide, o el usuario está bloqueado."""
        return await self._user_store.authenticate(tenant_id, username, password)

    # ===== Sesiones (ver `SessionStore`) =====

    async def create_session(self, user: User) -> Session:
        """Crea una sesión nueva para `user`, con vida fija (`SESSION_LIFETIME_HOURS`)."""
        return await self._session_store.create_session(user)

    async def get_session(self, token: str) -> Session | None:
        """Devuelve la `Session` de `token` si existe y no ha expirado; si no, `None`."""
        return await self._session_store.get_session(token)

    async def get_session_with_access(self, token: str) -> AuthenticatedSession | None:
        """Resuelve sesión + rol + nivel de instancia en una sola consulta (revisión 9)."""
        return await self._session_store.get_session_with_access(token)

    async def delete_session(self, token: str) -> None:
        """Logout selectivo: borra solo la sesión de `token`."""
        await self._session_store.delete_session(token)


__all__ = ["AuthStore", "AuthenticatedSession", "is_factory_admin_account"]
