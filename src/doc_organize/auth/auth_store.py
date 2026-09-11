"""
Almacen de tenants, roles, usuarios y sesiones (SQLite + WAL) para autenticacion
multi-usuario, multi-tenant y control de acceso por rol (revision 8 §2.7.2,
revision 9 roles y gestion de usuarios, rediseno Tenant/Role/User).
"""

import asyncio
import hashlib
import re
import secrets
import sqlite3
import unicodedata

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from uuid import uuid4

import aiosqlite

from doc_organize.core.constants import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_ROLE_NAME,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_TENANT_ID,
    ROLE_NAME_MAX_LENGTH,
    ROLE_NAME_PATTERN,
    SCRYPT_DKLEN,
    SCRYPT_MAXMEM,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
    SESSION_LIFETIME_HOURS,
    TENANT_ID_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_PATTERN,
)
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
from doc_organize.core.models import Role, Session, Tenant, User
from doc_organize.utils.logging import get_logger

_DEFAULT_AUTH_DB_PATH = Path.home() / ".doc_organize" / "auth.db"

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

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SLUG_COLLAPSE_DASHES = re.compile(r"-+")


def _slugify(name: str) -> str:
    """Deriva un identificador de tenant (slug) a partir de un nombre legible."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = ascii_name.strip().lower().replace(" ", "-")
    slug = _SLUG_INVALID_CHARS.sub("-", slug)
    slug = _SLUG_COLLAPSE_DASHES.sub("-", slug)
    return slug.strip("-")


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hashea `password` con `hashlib.scrypt`. Genera un salt nuevo si no se pasa uno.

    Sincrona y con coste de CPU/memoria deliberado (parametros OWASP) — se ejecuta
    siempre vía `asyncio.to_thread` desde los metodos async de `AuthStore` para no
    bloquear el event loop (mismo motivo por el que `hash_file()` usa `aiofiles`).
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=SCRYPT_DKLEN,
    )
    return salt, digest.hex()


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Compara `password` contra `expected_hash` en tiempo constante."""
    _, computed_hash = _hash_password(password, salt=salt)
    return secrets.compare_digest(computed_hash, expected_hash)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_role_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise AuthError("El nombre del rol no puede estar vacío.")
    if len(stripped) > ROLE_NAME_MAX_LENGTH:
        raise AuthError(f"El nombre del rol no puede superar los {ROLE_NAME_MAX_LENGTH} caracteres.")
    if not ROLE_NAME_PATTERN.match(stripped):
        raise AuthError("El nombre del rol solo puede contener letras, números, espacios, puntos, guiones y guion bajo.")
    return stripped


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


@dataclass
class AuthenticatedSession:
    """Sesión + acceso resueltos en una sola consulta (revisión 9).

    Evita que `AuthMiddleware` tenga que hacer una segunda consulta a `auth.db` por
    petición solo para saber si el usuario de la sesión es admin y qué rol tiene —
    ver `AuthStore.get_session_with_access()`.
    """

    session: Session
    role_id: str
    is_admin: bool
    must_change_password: bool
    is_instance_admin: bool


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
    `__aenter__()` igual que `_migrate_schema()`. `create_tenant()` (para tenants
    adicionales) ya NO aprovisiona usuario/rol: los da de alta un `is_instance_admin`
    o `user create` por CLI, porque no hay "rol admin de ESE tenant" que crear.

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

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self.db_path.parent.mkdir, parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        await self._migrate_schema()
        await self._ensure_default_tenant_bootstrap()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise AuthError("AuthStore debe usarse como context manager async ('async with').")
        return self._conn

    # ===== Migracion (bases de datos creadas antes de esta revision) =====

    async def _migrate_schema(self) -> None:
        """Aplica, de forma idempotente, todas las migraciones de esquema pendientes:
        columnas nuevas de `users`, reconstrucción de `roles` sin `tenant_id`, y
        retro-asignación de rol/`is_instance_admin` a filas preexistentes.

        Se ejecuta en cada apertura de `AuthStore` (mismo patron que el
        `CREATE TABLE IF NOT EXISTS` de `_SCHEMA`). SQLite no soporta
        `ADD COLUMN IF NOT EXISTS`, de ahi la comprobacion manual via
        `PRAGMA table_info`.
        """
        cursor = await self._connection.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cursor.fetchall()}

        altered = False
        if "role_id" not in columns:
            await self._connection.execute("ALTER TABLE users ADD COLUMN role_id TEXT REFERENCES roles(id)")
            altered = True
        if "must_change_password" not in columns:
            await self._connection.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
            altered = True
        if "is_blocked" not in columns:
            await self._connection.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")
            altered = True
        if "is_instance_admin" not in columns:
            await self._connection.execute("ALTER TABLE users ADD COLUMN is_instance_admin INTEGER NOT NULL DEFAULT 0")
            altered = True
        if altered:
            await self._connection.commit()

        await self._migrate_roles_schema()
        await self._backfill_missing_roles()
        await self._backfill_instance_admins()

    async def _migrate_roles_schema(self) -> None:
        """Reconstruye `roles` sin `tenant_id` (rediseño Tenant/Role/User: un rol ya
        no está ligado a un tenant) y retira `role_scan_roots` (`allowed_scan_roots`
        -> acceso implícito por proyecto, ver `web/dependencies.py`).

        SQLite no permite quitar una columna que participa en una FK o en un UNIQUE
        compuesto vía `ALTER TABLE ... DROP COLUMN` -- se reconstruye la tabla
        completa siguiendo el procedimiento oficial de SQLite para cambios de
        esquema no triviales: `foreign_keys=OFF` durante la ventana de recreación,
        tabla nueva con nombre temporal, copia de filas, `DROP` de la tabla vieja,
        `RENAME` de la nueva al nombre final, `foreign_keys=ON` de nuevo (ver
        https://www.sqlite.org/lang_altertable.html#otheralter). No se envuelve en
        try/except con rollback explícito: mismo criterio que el resto de esta
        función — un fallo aquí es una migración rota que debe propagarse, no
        enmascararse.

        Un nombre de rol duplicado entre dos tenants distintos (antes válido: único
        solo POR tenant) se desambigua añadiéndole el tenant de origen, porque el
        nuevo esquema exige `name` único globalmente.
        """
        cursor = await self._connection.execute("PRAGMA table_info(roles)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "tenant_id" not in columns:
            return  # instalación nueva, o ya migrada

        cursor = await self._connection.execute("SELECT id, tenant_id, name, is_admin, created_at FROM roles ORDER BY created_at")
        rows = await cursor.fetchall()

        final_names: dict[str, str] = {}
        seen_lower: set[str] = set()
        renamed_count = 0
        for role_id, tenant_id, name, _is_admin, _created_at in rows:
            candidate = name
            if candidate.lower() in seen_lower:
                candidate = f"{name} ({tenant_id})"
                suffix = 2
                while candidate.lower() in seen_lower:
                    candidate = f"{name} ({tenant_id}-{suffix})"
                    suffix += 1
                renamed_count += 1
            seen_lower.add(candidate.lower())
            final_names[role_id] = candidate

        await self._connection.execute("PRAGMA foreign_keys=OFF")
        try:
            await self._connection.execute(
                "CREATE TABLE roles_new (id TEXT PRIMARY KEY, name TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL, UNIQUE(name COLLATE NOCASE))"
            )
            for role_id, _tenant_id, _name, is_admin, created_at in rows:
                await self._connection.execute(
                    "INSERT INTO roles_new (id, name, is_admin, created_at) VALUES (?, ?, ?, ?)",
                    (role_id, final_names[role_id], is_admin, created_at),
                )
            await self._connection.execute("DROP TABLE roles")
            await self._connection.execute("ALTER TABLE roles_new RENAME TO roles")
            await self._connection.execute("DROP TABLE IF EXISTS role_scan_roots")
            await self._connection.commit()
        finally:
            await self._connection.execute("PRAGMA foreign_keys=ON")

        if renamed_count:
            self.logger.warning(
                f"Migración: {renamed_count} rol(es) renombrados por colisión de nombre global "
                "al retirar tenant_id de 'roles' (rediseño Tenant/Role/User)."
            )

    async def _backfill_missing_roles(self) -> None:
        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE role_id IS NULL")
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (missing_count,) = count_row
        if not missing_count:
            return

        admin_role_id = await self._get_or_create_admin_role_id()
        await self._connection.execute("UPDATE users SET role_id = ? WHERE role_id IS NULL", (admin_role_id,))
        await self._connection.commit()
        self.logger.info(f"Migración: {missing_count} usuario(s) sin rol retro-asignados al rol admin.")

    async def _backfill_instance_admins(self) -> None:
        """Promociona a `is_instance_admin=True` en una base de datos migrada desde
        antes de esta revisión (columna añadida con `0` para todas las filas).

        Solo promociona automáticamente al/los admin(es) del tenant `DEFAULT_TENANT_ID`
        (decisión de diseño: el resto de tenants preexistentes no ganan acceso de
        instancia sin acción explícita, para no escalar privilegios de más al
        actualizar). Si ninguno califica (el tenant por defecto no existía, o no
        tenía ningún admin), promociona al usuario más antiguo de toda la
        instalación, para que nunca quede sin ningún `is_instance_admin` tras
        migrar (`main.py user set-instance-admin` es la vía manual para ajustarlo
        después).
        """
        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE is_instance_admin = 1")
        count_row = await cursor.fetchone()
        assert count_row is not None
        (existing,) = count_row
        if existing:
            return  # instalación nueva (bootstrap la crea directamente) o ya migrada

        cursor = await self._connection.execute(
            "SELECT u.id FROM users u JOIN roles r ON u.role_id = r.id WHERE u.tenant_id = ? AND r.is_admin = 1 ORDER BY u.created_at",
            (DEFAULT_TENANT_ID,),
        )
        promoted_ids = [row[0] for row in await cursor.fetchall()]

        if not promoted_ids:
            cursor = await self._connection.execute("SELECT id FROM users ORDER BY created_at LIMIT 1")
            row = await cursor.fetchone()
            if row is None:
                return  # instalación realmente nueva: sin usuarios todavía
            promoted_ids = [row[0]]

        await self._connection.executemany(
            "UPDATE users SET is_instance_admin = 1 WHERE id = ?",
            [(user_id,) for user_id in promoted_ids],
        )
        await self._connection.commit()
        self.logger.warning(
            f"Migración: {len(promoted_ids)} usuario(s) promocionados a is_instance_admin "
            "(rediseño Tenant/Role/User) -- revisa quién debería conservar ese nivel."
        )

    async def _ensure_default_tenant_bootstrap(self) -> None:
        """Garantiza que `DEFAULT_TENANT_ID` existe, con su rol y usuario admin de
        fábrica, sin aprovisionamiento manual previo. Se ejecuta en cada apertura
        de `AuthStore` (CLI y web por igual), idempotente igual que `_migrate_schema()`.

        Exclusivo de `DEFAULT_TENANT_ID`: `create_tenant()` (para cualquier otro
        tenant) ya no aprovisiona usuario/rol -- ver su docstring. Si el tenant por
        defecto se borra (`delete_tenant`), esta función lo vuelve a crear de
        fábrica (con un usuario `admin`/contraseña de fábrica nuevo,
        `must_change_password=True`) la siguiente vez que se abra `AuthStore` --
        comportamiento intencional, no un cabo suelto: nunca deja la instalación
        sin ninguna forma de entrar.
        """
        if await self.tenant_exists(DEFAULT_TENANT_ID):
            return

        tenant = Tenant(id=DEFAULT_TENANT_ID, name="Default", created_at=_now_iso())
        admin_role_id = await self._get_or_create_admin_role_id()
        salt, password_hash = await asyncio.to_thread(_hash_password, DEFAULT_ADMIN_PASSWORD)
        admin_user = User(
            id=str(uuid4()),
            tenant_id=DEFAULT_TENANT_ID,
            username=DEFAULT_ADMIN_USERNAME,
            role_id=admin_role_id,
            must_change_password=True,
            is_instance_admin=True,
            created_at=tenant.created_at,
        )
        try:
            await self._connection.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant.id, tenant.name, tenant.created_at),
            )
            await self._insert_user_row(admin_user, password_hash, salt)
            await self._connection.commit()
        except aiosqlite.IntegrityError:
            # Ventana de carrera entre el tenant_exists() de arriba y este INSERT:
            # otra apertura concurrente de AuthStore ya lo creó -- nada que hacer.
            await self._connection.rollback()
            return
        self.logger.info(f"Bootstrap: tenant '{DEFAULT_TENANT_ID}' creado con usuario admin de fábrica ('{DEFAULT_ADMIN_USERNAME}').")

    async def _get_or_create_admin_role_id(self) -> str:
        cursor = await self._connection.execute("SELECT id FROM roles WHERE is_admin = 1 ORDER BY created_at LIMIT 1")
        row = await cursor.fetchone()
        if row is not None:
            return str(row[0])

        role = Role(id=str(uuid4()), name=DEFAULT_ADMIN_ROLE_NAME, is_admin=True, created_at=_now_iso())
        await self._insert_role_row(role)
        return role.id

    # ===== Insercion de filas (sin commit — los llamadores deciden la transaccion) =====

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

    async def _load_role_project_names(self, role_id: str) -> list[str]:
        cursor = await self._connection.execute("SELECT project_name FROM role_projects WHERE role_id = ? ORDER BY project_name", (role_id,))
        return [row[0] for row in await cursor.fetchall()]

    # ===== Tenants =====

    async def create_tenant(self, name: str) -> Tenant:
        """Crea un tenant nuevo; su `id` se deriva de `name` (slug).

        A diferencia de la revisión 9, ya NO aprovisiona automáticamente un rol ni
        un usuario admin: `Role` ya no está ligado a un tenant (rediseño
        Tenant/Role/User), así que no hay "rol admin de ESTE tenant" que crear. El
        primer usuario de un tenant nuevo lo da de alta un `is_instance_admin`
        (pantalla "Tenants y usuarios") o `user create` por CLI, asignándole
        cualquier rol `is_admin=True` ya existente (o uno nuevo). Solo
        `DEFAULT_TENANT_ID` recibe bootstrap automático, vía
        `_ensure_default_tenant_bootstrap()` en `__aenter__`, no este método.

        Raises:
            AuthError: Si `name` esta vacio o no produce un slug valido.
            TenantAlreadyExistsError: Si ya existe un tenant con ese `id`.
        """
        stripped = name.strip()
        if not stripped:
            raise AuthError("El nombre del tenant no puede estar vacío.")

        slug = _slugify(stripped)
        if not slug:
            raise AuthError(f"No se pudo derivar un identificador válido de '{name}'.")
        if len(slug) > TENANT_ID_MAX_LENGTH:
            raise AuthError(f"El identificador del tenant no puede superar los {TENANT_ID_MAX_LENGTH} caracteres: '{slug}'.")

        if await self.tenant_exists(slug):
            raise TenantAlreadyExistsError(slug)

        tenant = Tenant(id=slug, name=stripped, created_at=_now_iso())
        try:
            await self._connection.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant.id, tenant.name, tenant.created_at),
            )
            await self._connection.commit()
        except aiosqlite.IntegrityError as exc:
            # Ventana de carrera entre el `tenant_exists()` de arriba y este INSERT:
            # dos peticiones concurrentes con el mismo nombre pueden pasar ambas el
            # pre-check antes de que ninguna haga commit. El INSERT (con su índice
            # UNIQUE/PK real) es la última línea de defensa — nunca debe escapar un
            # IntegrityError en bruto hasta la API.
            await self._connection.rollback()
            raise TenantAlreadyExistsError(slug) from exc
        except Exception:
            await self._connection.rollback()
            raise

        self.logger.info(f"Tenant creado: '{tenant.id}' ({tenant.name}), sin usuarios (alta manual pendiente).")
        return tenant

    async def tenant_exists(self, tenant_id: str) -> bool:
        """True si hay un tenant registrado con ese `id` exacto."""
        cursor = await self._connection.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,))
        return await cursor.fetchone() is not None

    async def list_tenants(self) -> list[Tenant]:
        """Lista todos los tenants (pantalla cruzada "Tenants y usuarios", solo `is_instance_admin`)."""
        cursor = await self._connection.execute("SELECT id, name, created_at FROM tenants ORDER BY created_at")
        return [Tenant(id=row[0], name=row[1], created_at=row[2]) for row in await cursor.fetchall()]

    async def delete_tenant(self, tenant_id: str, *, has_projects: bool) -> None:
        """Elimina un tenant. Solo si no tiene usuarios NI proyectos asociados.

        `has_projects` lo resuelve el llamador vía `ProjectRegistry` — `AuthStore`
        no depende de `projects.py` (mismo criterio DIP que el resto del módulo: la
        pertenencia de un proyecto a un tenant vive en `ProjectRegistry`, no aquí).

        `DEFAULT_TENANT_ID` no es un caso especial aquí: se puede eliminar igual
        que cualquier otro, y `_ensure_default_tenant_bootstrap()` lo recreará de
        fábrica (con un usuario admin nuevo) la próxima vez que se abra `AuthStore`.

        Raises:
            TenantNotFoundError: Si `tenant_id` no existe.
            TenantInUseError: Si tiene usuarios o proyectos asociados.
        """
        if not await self.tenant_exists(tenant_id):
            raise TenantNotFoundError(tenant_id)

        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE tenant_id = ?", (tenant_id,))
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (user_count,) = count_row
        if user_count > 0:
            raise TenantInUseError(f"El tenant '{tenant_id}' tiene {user_count} usuario(s); elimínalos antes de borrar el tenant.")
        if has_projects:
            raise TenantInUseError(f"El tenant '{tenant_id}' tiene proyectos asociados; elimínalos antes de borrar el tenant.")

        await self._connection.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        await self._connection.commit()

    async def _role_name_taken(self, name: str, *, exclude_role_id: str | None = None) -> bool:
        if exclude_role_id is None:
            cursor = await self._connection.execute("SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE", (name,))
        else:
            cursor = await self._connection.execute(
                "SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE AND id != ?",
                (name, exclude_role_id),
            )
        return await cursor.fetchone() is not None

    async def _username_taken(self, tenant_id: str, username: str) -> bool:
        cursor = await self._connection.execute("SELECT 1 FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE", (tenant_id, username))
        return await cursor.fetchone() is not None

    # ===== Roles (globales — rediseño Tenant/Role/User: sin tenant_id) =====

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

        role = Role(id=str(uuid4()), name=stripped_name, is_admin=is_admin, project_names=deduped_projects, created_at=_now_iso())
        try:
            await self._insert_role_row(role)
            await self._connection.commit()
        except aiosqlite.IntegrityError as exc:
            # Misma ventana de carrera que `create_tenant`: el SELECT de arriba no
            # es la única defensa, el UNIQUE(name) del esquema lo es.
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

    async def delete_role(self, role_id: str) -> None:
        """Elimina un rol.

        Raises:
            RoleNotFoundError: Si no existe.
            RoleInUseError: Si algún usuario (de cualquier tenant) lo tiene
                asignado, o si es el último rol `is_admin` de todo el sistema
                (evita dejar la instalación entera sin ninguna forma de gestionar
                ningún tenant — la guarda ya no es por tenant, porque el rol
                tampoco lo es).
        """
        role = await self.get_role(role_id)

        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE role_id = ?", (role_id,))
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (user_count,) = count_row
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

    # ===== Usuarios =====

    async def create_user(self, tenant_id: str, username: str, password: str, role_id: str | None = None, must_change_password: bool = False) -> User:
        """Crea un usuario dentro de `tenant_id`; `username` es único por tenant (case-insensitive).

        Args:
            role_id: Rol a asignar. Si se omite, se usa el rol admin global
                (siempre existe: lo crea el bootstrap del tenant por defecto o
                `_get_or_create_admin_role_id()`) — preserva el comportamiento
                previo, donde todo usuario nuevo sin rol explícito gestionaba
                todos los proyectos de su tenant por igual.
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

        if not await self.tenant_exists(tenant_id):
            raise TenantNotFoundError(tenant_id)

        if role_id is None:
            role_id = await self._get_or_create_admin_role_id()
        else:
            await self.get_role(role_id)  # RoleNotFoundError si no existe

        if await self._username_taken(tenant_id, stripped_username):
            raise UserAlreadyExistsError(stripped_username, tenant_id)

        salt, password_hash = await asyncio.to_thread(_hash_password, password)
        user = User(
            id=str(uuid4()),
            tenant_id=tenant_id,
            username=stripped_username,
            role_id=role_id,
            must_change_password=must_change_password,
            created_at=_now_iso(),
        )
        try:
            await self._insert_user_row(user, password_hash, salt)
            await self._connection.commit()
        except aiosqlite.IntegrityError as exc:
            # Misma ventana de carrera que `create_tenant`/`create_role`: el SELECT
            # de arriba no es la única defensa, el UNIQUE(tenant_id, username) del
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
            old_role = await self.get_role(current.role_id)
            new_role = await self.get_role(role_id)
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
            new_salt, new_hash = await asyncio.to_thread(_hash_password, password)
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
            role = await self.get_role(current.role_id)
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
        role = await self.get_role(user.role_id)
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
        if not await asyncio.to_thread(_verify_password, current_password, salt, password_hash):
            return False
        if not new_password:
            raise AuthError("La nueva contraseña no puede estar vacía.")

        new_salt, new_hash = await asyncio.to_thread(_hash_password, new_password)
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
        is_valid = await asyncio.to_thread(_verify_password, password, salt, password_hash)
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

    # ===== Sesiones =====

    async def create_session(self, user: User) -> Session:
        """Crea una sesión nueva para `user`, con vida fija (`SESSION_LIFETIME_HOURS`).

        Antes de insertar, purga cualquier sesión ya expirada (de cualquier
        usuario/tenant): único punto de limpieza de `sessions` — se ejecuta una
        vez por login, no en cada apertura de `AuthStore` (que sí ocurre en cada
        petición autenticada vía `authenticate_session()`, demasiado caliente
        para una escritura). `get_session()`/`get_session_with_access()` ya
        filtran las expiradas en lectura, pero nunca las borraban — sin este
        barrido la tabla crecía sin límite a lo largo de la vida de `auth.db`.
        """
        now = datetime.now(UTC)
        await self._connection.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
        session = Session(
            token=secrets.token_urlsafe(32),
            user_id=user.id,
            tenant_id=user.tenant_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=SESSION_LIFETIME_HOURS)).isoformat(),
        )
        await self._connection.execute(
            "INSERT INTO sessions (token, user_id, tenant_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (session.token, session.user_id, session.tenant_id, session.created_at, session.expires_at),
        )
        await self._connection.commit()
        return session

    async def get_session(self, token: str) -> Session | None:
        """Devuelve la `Session` de `token` si existe y no ha expirado; si no, `None`."""
        cursor = await self._connection.execute(
            "SELECT token, user_id, tenant_id, created_at, expires_at FROM sessions WHERE token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        session = Session(token=row[0], user_id=row[1], tenant_id=row[2], created_at=row[3], expires_at=row[4])
        if datetime.fromisoformat(session.expires_at) <= datetime.now(UTC):
            return None
        return session

    async def get_session_with_access(self, token: str) -> AuthenticatedSession | None:
        """Resuelve sesión + rol + nivel de instancia en una sola consulta (revisión 9).

        Usada por `AuthMiddleware` en lugar de `get_session()` + una consulta
        aparte de rol: evita una segunda ida a `auth.db` por petición solo para
        saber si el usuario es admin, qué proyectos puede ver, y si tiene
        `is_instance_admin`. Un usuario bloqueado no tiene sesiones que resolver
        (`set_user_blocked` las borra en la misma transacción que fija
        `is_blocked`), así que esta consulta no necesita comprobarlo de nuevo.
        """
        cursor = await self._connection.execute(
            "SELECT s.token, s.user_id, s.tenant_id, s.created_at, s.expires_at, "
            "u.role_id, u.must_change_password, u.is_instance_admin, r.is_admin "
            "FROM sessions s JOIN users u ON s.user_id = u.id JOIN roles r ON u.role_id = r.id "
            "WHERE s.token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        token_value, user_id, tenant_id, created_at, expires_at, role_id, must_change_password, is_instance_admin, is_admin = row
        session = Session(token=token_value, user_id=user_id, tenant_id=tenant_id, created_at=created_at, expires_at=expires_at)
        if datetime.fromisoformat(session.expires_at) <= datetime.now(UTC):
            return None

        return AuthenticatedSession(
            session=session,
            role_id=role_id,
            is_admin=bool(is_admin),
            must_change_password=bool(must_change_password),
            is_instance_admin=bool(is_instance_admin),
        )

    async def delete_session(self, token: str) -> None:
        """Logout selectivo: borra solo la sesión de `token`.

        No afecta a otras sesiones del mismo usuario ni de ningún otro — es la
        propiedad explícitamente pedida por el usuario para `§2.7.2`.
        """
        await self._connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await self._connection.commit()


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


__all__ = ["AuthStore", "AuthenticatedSession", "is_factory_admin_account"]
