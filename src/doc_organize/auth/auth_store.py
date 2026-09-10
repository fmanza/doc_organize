"""
Almacen de tenants, roles, usuarios y sesiones (SQLite + WAL) para autenticacion
multi-usuario, multi-tenant y control de acceso por rol (revision 8 §2.7.2,
revision 9 roles y gestion de usuarios).
"""

import asyncio
import hashlib
import re
import secrets
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
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    TenantAlreadyExistsError,
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
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, name COLLATE NOCASE)
);
CREATE TABLE IF NOT EXISTS role_projects (
    role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    project_name TEXT NOT NULL,
    PRIMARY KEY (role_id, project_name)
);
CREATE TABLE IF NOT EXISTS role_scan_roots (
    role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    root_path TEXT NOT NULL,
    PRIMARY KEY (role_id, root_path)
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role_id TEXT REFERENCES roles(id),
    must_change_password INTEGER NOT NULL DEFAULT 0,
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


class AuthStore:
    """Almacen de tenants, roles, usuarios y sesiones para autenticacion multi-tenant.

    SQLite+WAL en `~/.doc_organize/auth.db`, no el patron JSON+asyncio.Lock de
    `ProjectRegistry`: a diferencia de `projects.json`, aqui hay relaciones reales
    entre varias entidades (tenant -> rol -> usuario -> sesion) que se benefician de
    FK real e integridad referencial. Las contrasenas se hashean con
    `hashlib.scrypt` (parametros OWASP) + salt aleatorio por usuario; los tokens de
    sesion son opacos (`secrets.token_urlsafe`), nunca derivados de la contrasena.

    Cada tenant nuevo (`create_tenant`) recibe automaticamente, en una unica
    transaccion, un rol `admin` (ve todos los proyectos del tenant) y un usuario
    `admin`/`admin` marcado con `must_change_password=True` (revision 9) — sin este
    bootstrap no habria forma de crear el primer usuario de un tenant.

    Attributes:
        db_path (Path): Ruta al archivo SQLite.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     db_path = Path(tempfile.mkdtemp()) / "auth.db"
        ...     async with AuthStore(db_path) as store:
        ...         tenant = await store.create_tenant("Acme Corp")  # crea admin/admin
        ...         role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto A"])
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

    # ===== Migracion (bases de datos creadas antes de la revision 9) =====

    async def _migrate_schema(self) -> None:
        """Anade `role_id`/`must_change_password` a `users` si faltan, y retro-asigna
        el rol admin del tenant a cualquier usuario preexistente que quede sin rol.

        Idempotente: se ejecuta en cada apertura de `AuthStore` (mismo patron que el
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
        if altered:
            await self._connection.commit()

        await self._backfill_missing_roles()

    async def _backfill_missing_roles(self) -> None:
        cursor = await self._connection.execute("SELECT DISTINCT tenant_id FROM users WHERE role_id IS NULL")
        tenant_ids = [row[0] for row in await cursor.fetchall()]
        if not tenant_ids:
            return

        for tenant_id in tenant_ids:
            admin_role_id = await self._get_or_create_admin_role_id(tenant_id)
            await self._connection.execute(
                "UPDATE users SET role_id = ? WHERE tenant_id = ? AND role_id IS NULL",
                (admin_role_id, tenant_id),
            )
            self.logger.info(f"Migración: usuarios sin rol de '{tenant_id}' retro-asignados al rol admin.")
        await self._connection.commit()

    async def _get_or_create_admin_role_id(self, tenant_id: str) -> str:
        cursor = await self._connection.execute(
            "SELECT id FROM roles WHERE tenant_id = ? AND is_admin = 1 ORDER BY created_at LIMIT 1",
            (tenant_id,),
        )
        row = await cursor.fetchone()
        if row is not None:
            return str(row[0])

        role = Role(id=str(uuid4()), tenant_id=tenant_id, name=DEFAULT_ADMIN_ROLE_NAME, is_admin=True, created_at=_now_iso())
        await self._insert_role_row(role)
        return role.id

    # ===== Insercion de filas (sin commit — los llamadores deciden la transaccion) =====

    async def _insert_role_row(self, role: Role) -> None:
        await self._connection.execute(
            "INSERT INTO roles (id, tenant_id, name, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (role.id, role.tenant_id, role.name, int(role.is_admin), role.created_at),
        )
        if role.project_names:
            await self._connection.executemany(
                "INSERT INTO role_projects (role_id, project_name) VALUES (?, ?)",
                [(role.id, project_name) for project_name in role.project_names],
            )
        if role.allowed_scan_roots:
            await self._connection.executemany(
                "INSERT INTO role_scan_roots (role_id, root_path) VALUES (?, ?)",
                [(role.id, root_path) for root_path in role.allowed_scan_roots],
            )

    async def _replace_role_associations(self, role_id: str, project_names: list[str], scan_roots: list[str]) -> None:
        """Reemplaza por completo `role_projects`/`role_scan_roots` de `role_id` (usado por
        `update_role`, sin commit — el llamador decide la transaccion)."""
        await self._connection.execute("DELETE FROM role_projects WHERE role_id = ?", (role_id,))
        if project_names:
            await self._connection.executemany(
                "INSERT INTO role_projects (role_id, project_name) VALUES (?, ?)",
                [(role_id, project_name) for project_name in project_names],
            )
        await self._connection.execute("DELETE FROM role_scan_roots WHERE role_id = ?", (role_id,))
        if scan_roots:
            await self._connection.executemany(
                "INSERT INTO role_scan_roots (role_id, root_path) VALUES (?, ?)",
                [(role_id, root_path) for root_path in scan_roots],
            )

    async def _insert_user_row(self, user: User, password_hash: str, salt: str) -> None:
        await self._connection.execute(
            "INSERT INTO users (id, tenant_id, username, password_hash, password_salt, role_id, must_change_password, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user.id,
                user.tenant_id,
                user.username,
                password_hash,
                salt,
                user.role_id,
                int(user.must_change_password),
                user.created_at,
            ),
        )

    async def _load_role_project_names(self, role_id: str) -> list[str]:
        cursor = await self._connection.execute("SELECT project_name FROM role_projects WHERE role_id = ? ORDER BY project_name", (role_id,))
        return [row[0] for row in await cursor.fetchall()]

    async def _load_role_scan_roots(self, role_id: str) -> list[str]:
        cursor = await self._connection.execute("SELECT root_path FROM role_scan_roots WHERE role_id = ? ORDER BY root_path", (role_id,))
        return [row[0] for row in await cursor.fetchall()]

    # ===== Tenants =====

    async def create_tenant(self, name: str) -> Tenant:
        """Crea un tenant nuevo; su `id` se deriva de `name` (slug).

        Bootstrap automático (revisión 9), en la misma transacción que el `INSERT`
        del tenant: rol `admin` (`is_admin=True`) + usuario `admin`/`admin` con
        `must_change_password=True`. Si cualquiera de las tres inserciones falla, se
        hace rollback completo — nunca queda un tenant sin admin.

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
        admin_role = Role(id=str(uuid4()), tenant_id=slug, name=DEFAULT_ADMIN_ROLE_NAME, is_admin=True, created_at=tenant.created_at)
        salt, password_hash = await asyncio.to_thread(_hash_password, DEFAULT_ADMIN_PASSWORD)
        admin_user = User(
            id=str(uuid4()),
            tenant_id=slug,
            username=DEFAULT_ADMIN_USERNAME,
            role_id=admin_role.id,
            must_change_password=True,
            created_at=tenant.created_at,
        )

        try:
            await self._connection.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant.id, tenant.name, tenant.created_at),
            )
            await self._insert_role_row(admin_role)
            await self._insert_user_row(admin_user, password_hash, salt)
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

        self.logger.info(f"Tenant creado: '{tenant.id}' ({tenant.name}), con rol y usuario admin por defecto")
        return tenant

    async def tenant_exists(self, tenant_id: str) -> bool:
        """True si hay un tenant registrado con ese `id` exacto."""
        cursor = await self._connection.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,))
        return await cursor.fetchone() is not None

    async def _role_name_taken(self, tenant_id: str, name: str, *, exclude_role_id: str | None = None) -> bool:
        if exclude_role_id is None:
            cursor = await self._connection.execute("SELECT 1 FROM roles WHERE tenant_id = ? AND name = ? COLLATE NOCASE", (tenant_id, name))
        else:
            cursor = await self._connection.execute(
                "SELECT 1 FROM roles WHERE tenant_id = ? AND name = ? COLLATE NOCASE AND id != ?",
                (tenant_id, name, exclude_role_id),
            )
        return await cursor.fetchone() is not None

    async def _username_taken(self, tenant_id: str, username: str) -> bool:
        cursor = await self._connection.execute("SELECT 1 FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE", (tenant_id, username))
        return await cursor.fetchone() is not None

    # ===== Roles =====

    async def create_role(
        self,
        tenant_id: str,
        name: str,
        is_admin: bool = False,
        project_names: list[str] | None = None,
        allowed_scan_roots: list[str] | None = None,
    ) -> Role:
        """Crea un rol dentro de `tenant_id`; `name` es único por tenant (case-insensitive).

        Args:
            allowed_scan_roots: Rutas del sistema de archivos que este rol puede
                escanear vía `/api/projects/{name}/scan` (revisión de seguridad:
                sin esto, cualquier rol con acceso a un proyecto podía escanear
                cualquier ruta legible por el servidor, evadiendo `project_names`).
                Vacía por defecto — un rol restringido no puede escanear ninguna
                ruta externa hasta que un admin le asigne al menos una.

        Raises:
            AuthError: Si `name` no cumple las reglas mínimas, o si `is_admin=True`
                se combina con una lista de proyectos o de raíces de escaneo no
                vacía (un rol admin ve todos los proyectos del tenant y puede
                escanear cualquier ruta; una lista explícita sería ambigua).
            TenantNotFoundError: Si `tenant_id` no existe.
            RoleAlreadyExistsError: Si ya existe ese `name` en el tenant.
        """
        stripped_name = _validate_role_name(name)
        deduped_projects = list(dict.fromkeys(project_names or []))
        deduped_scan_roots = list(dict.fromkeys(allowed_scan_roots or []))
        if is_admin and deduped_projects:
            raise AuthError("Un rol admin ve todos los proyectos del tenant; no se le puede asignar una lista de proyectos.")
        if is_admin and deduped_scan_roots:
            raise AuthError("Un rol admin puede escanear cualquier ruta; no se le puede asignar una lista de raíces de escaneo.")

        if not await self.tenant_exists(tenant_id):
            raise TenantNotFoundError(tenant_id)

        if await self._role_name_taken(tenant_id, stripped_name):
            raise RoleAlreadyExistsError(stripped_name, tenant_id)

        role = Role(
            id=str(uuid4()),
            tenant_id=tenant_id,
            name=stripped_name,
            is_admin=is_admin,
            project_names=deduped_projects,
            allowed_scan_roots=deduped_scan_roots,
            created_at=_now_iso(),
        )
        try:
            await self._insert_role_row(role)
            await self._connection.commit()
        except aiosqlite.IntegrityError as exc:
            # Misma ventana de carrera que `create_tenant`: el SELECT de arriba no
            # es la única defensa, el UNIQUE(tenant_id, name) del esquema lo es.
            await self._connection.rollback()
            raise RoleAlreadyExistsError(stripped_name, tenant_id) from exc
        self.logger.info(f"Rol creado: '{role.name}' en tenant '{tenant_id}' (is_admin={is_admin})")
        return role

    async def list_roles(self, tenant_id: str) -> list[Role]:
        """Lista los roles de `tenant_id`, ordenados por fecha de creación."""
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, name, is_admin, created_at FROM roles WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,),
        )
        rows = await cursor.fetchall()
        roles = []
        for row in rows:
            project_names = await self._load_role_project_names(row[0])
            allowed_scan_roots = await self._load_role_scan_roots(row[0])
            roles.append(
                Role(
                    id=row[0],
                    tenant_id=row[1],
                    name=row[2],
                    is_admin=bool(row[3]),
                    project_names=project_names,
                    allowed_scan_roots=allowed_scan_roots,
                    created_at=row[4],
                )
            )
        return roles

    async def get_role(self, tenant_id: str, role_id: str) -> Role:
        """Devuelve el rol `role_id` de `tenant_id`.

        Raises:
            RoleNotFoundError: Si no existe, o pertenece a otro tenant (mismo
                criterio de no-enumeración cross-tenant que `ProjectRegistry`).
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, name, is_admin, created_at FROM roles WHERE id = ? AND tenant_id = ?",
            (role_id, tenant_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RoleNotFoundError(role_id, tenant_id)
        project_names = await self._load_role_project_names(row[0])
        allowed_scan_roots = await self._load_role_scan_roots(row[0])
        return Role(
            id=row[0],
            tenant_id=row[1],
            name=row[2],
            is_admin=bool(row[3]),
            project_names=project_names,
            allowed_scan_roots=allowed_scan_roots,
            created_at=row[4],
        )

    @staticmethod
    def _resolve_role_update(
        current: Role,
        *,
        name: str | None,
        is_admin: bool | None,
        project_names: list[str] | None,
        allowed_scan_roots: list[str] | None,
    ) -> tuple[str, bool, list[str], list[str]]:
        """Calcula name/is_admin/project_names/allowed_scan_roots nuevos para `update_role`
        a partir de `current` y los campos pasados (solo los no-`None` cambian), validando
        las combinaciones prohibidas. No toca la base de datos.

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
        new_scan_roots = current.allowed_scan_roots if allowed_scan_roots is None else list(dict.fromkeys(allowed_scan_roots))
        if is_admin is False and current.allowed_scan_roots and allowed_scan_roots is None:
            new_scan_roots = []

        if new_is_admin and new_project_names:
            raise AuthError("Un rol admin ve todos los proyectos del tenant; no se le puede asignar una lista de proyectos.")
        if new_is_admin and new_scan_roots:
            raise AuthError("Un rol admin puede escanear cualquier ruta; no se le puede asignar una lista de raíces de escaneo.")

        return new_name, new_is_admin, new_project_names, new_scan_roots

    async def update_role(
        self,
        tenant_id: str,
        role_id: str,
        *,
        name: str | None = None,
        is_admin: bool | None = None,
        project_names: list[str] | None = None,
        allowed_scan_roots: list[str] | None = None,
    ) -> Role:
        """Actualiza nombre/`is_admin`/proyectos/raíces de escaneo de un rol. Solo los
        campos pasados cambian.

        `project_names`/`allowed_scan_roots`, si se pasan, reemplazan la lista
        completa (no la combinan con la existente).

        Raises:
            AuthError: Si `is_admin` pasa explícitamente de `True` a `False` sin
                pasar `project_names` en la misma llamada — degradar un rol admin
                sin decir a qué proyectos queda restringido dejaría la lista vacía
                en silencio (pierde todo acceso sin que quien llama lo pidiera
                explícitamente). `allowed_scan_roots` no tiene esta misma exigencia:
                queda vacía por defecto tras degradar (sin capacidad de escaneo
                externo), que es el lado seguro, no una pérdida sorprendente de
                acceso previamente concedido a ese rol.
        """
        current = await self.get_role(tenant_id, role_id)
        new_name, new_is_admin, new_project_names, new_scan_roots = self._resolve_role_update(
            current,
            name=name,
            is_admin=is_admin,
            project_names=project_names,
            allowed_scan_roots=allowed_scan_roots,
        )

        if new_name.lower() != current.name.lower() and await self._role_name_taken(tenant_id, new_name, exclude_role_id=role_id):
            raise RoleAlreadyExistsError(new_name, tenant_id)

        await self._connection.execute("UPDATE roles SET name = ?, is_admin = ? WHERE id = ?", (new_name, int(new_is_admin), role_id))
        await self._replace_role_associations(role_id, new_project_names, new_scan_roots)
        await self._connection.commit()
        return Role(
            id=role_id,
            tenant_id=tenant_id,
            name=new_name,
            is_admin=new_is_admin,
            project_names=new_project_names,
            allowed_scan_roots=new_scan_roots,
            created_at=current.created_at,
        )

    async def delete_role(self, tenant_id: str, role_id: str) -> None:
        """Elimina un rol.

        Raises:
            RoleNotFoundError: Si no existe en `tenant_id`.
            RoleInUseError: Si algún usuario lo tiene asignado, o si es el último
                rol `is_admin` del tenant (evita dejar el tenant sin forma de
                gestionarse).
        """
        role = await self.get_role(tenant_id, role_id)

        cursor = await self._connection.execute("SELECT COUNT(*) FROM users WHERE role_id = ?", (role_id,))
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (user_count,) = count_row
        if user_count > 0:
            raise RoleInUseError(f"El rol '{role.name}' está asignado a {user_count} usuario(s); reasígnalos antes de eliminarlo.")

        if role.is_admin:
            cursor = await self._connection.execute(
                "SELECT COUNT(*) FROM roles WHERE tenant_id = ? AND is_admin = 1 AND id != ?",
                (tenant_id, role_id),
            )
            count_row = await cursor.fetchone()
            assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
            (other_admin_roles,) = count_row
            if other_admin_roles == 0:
                raise RoleInUseError("No se puede eliminar el último rol admin del tenant.")

        await self._connection.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        await self._connection.commit()

    async def can_access_project(self, tenant_id: str, role_id: str, project_name: str) -> bool:
        """`True` si el rol `role_id` de `tenant_id` puede acceder a `project_name`.

        Un rol `is_admin` accede a cualquier proyecto del tenant sin estar listado
        en `role_projects`. Comparación de nombre case-insensitive (mismo criterio
        que `ProjectRegistry.get_project()`).
        """
        cursor = await self._connection.execute("SELECT is_admin FROM roles WHERE id = ? AND tenant_id = ?", (role_id, tenant_id))
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
            role_id: Rol a asignar. Si se omite, se usa el rol admin del tenant
                (siempre existe: lo crea `create_tenant`) — preserva el
                comportamiento previo a la revisión 9, donde todo usuario nuevo
                gestionaba todos los proyectos del tenant por igual.
            must_change_password: Si `True`, el usuario debe cambiar su contraseña
                en el primer login (`AuthMiddleware`). `False` por defecto para
                usuarios creados explícitamente por un admin con una contraseña
                elegida por ellos mismos.

        Raises:
            AuthError: Si `username`/`password` no cumplen las reglas mínimas.
            TenantNotFoundError: Si `tenant_id` no existe.
            RoleNotFoundError: Si `role_id` no existe en `tenant_id`.
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
            role_id = await self._get_or_create_admin_role_id(tenant_id)
        else:
            await self.get_role(tenant_id, role_id)  # RoleNotFoundError si no existe/otro tenant

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
            "SELECT id, tenant_id, username, role_id, must_change_password, created_at FROM users WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,),
        )
        rows = await cursor.fetchall()
        return [User(id=r[0], tenant_id=r[1], username=r[2], role_id=r[3], must_change_password=bool(r[4]), created_at=r[5]) for r in rows]

    async def get_user(self, tenant_id: str, user_id: str) -> User:
        """Devuelve el usuario `user_id` de `tenant_id`.

        Raises:
            UserNotFoundError: Si no existe, o pertenece a otro tenant.
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, role_id, must_change_password, created_at FROM users WHERE id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise UserNotFoundError(user_id, tenant_id)
        return User(id=row[0], tenant_id=row[1], username=row[2], role_id=row[3], must_change_password=bool(row[4]), created_at=row[5])

    async def _count_other_admins(self, tenant_id: str, exclude_user_id: str) -> int:
        cursor = await self._connection.execute(
            "SELECT COUNT(*) FROM users u JOIN roles r ON u.role_id = r.id WHERE u.tenant_id = ? AND r.is_admin = 1 AND u.id != ?",
            (tenant_id, exclude_user_id),
        )
        count_row = await cursor.fetchone()
        assert count_row is not None  # SELECT COUNT(*) siempre devuelve una fila
        (count,) = count_row
        return int(count)

    async def update_user(self, tenant_id: str, user_id: str, *, role_id: str | None = None, password: str | None = None) -> User:
        """Actualiza el rol y/o restablece la contraseña de un usuario (uso admin).

        Restablecer `password` fija `must_change_password=True` — el usuario debe
        elegir una nueva contraseña en su próximo login, igual que el admin de
        bootstrap.

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleNotFoundError: Si `role_id` no existe en `tenant_id`.
            RoleInUseError: Si el cambio de rol dejaría al tenant sin ningún
                usuario admin.
            AuthError: Si `password` se pasa vacía.
        """
        current = await self.get_user(tenant_id, user_id)

        new_role_id = current.role_id
        if role_id is not None and role_id != current.role_id:
            old_role = await self.get_role(tenant_id, current.role_id)
            new_role = await self.get_role(tenant_id, role_id)
            if old_role.is_admin and not new_role.is_admin and await self._count_other_admins(tenant_id, user_id) == 0:
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
            created_at=current.created_at,
        )

    async def delete_user(self, tenant_id: str, user_id: str) -> None:
        """Elimina un usuario (sus sesiones se borran en cascada vía FK).

        Raises:
            UserNotFoundError: Si `user_id` no existe en `tenant_id`.
            RoleInUseError: Si es el último usuario admin del tenant.
        """
        user = await self.get_user(tenant_id, user_id)
        role = await self.get_role(tenant_id, user.role_id)
        if role.is_admin and await self._count_other_admins(tenant_id, user_id) == 0:
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
        """Valida credenciales; `None` si el tenant/usuario no existe o la contraseña no coincide.

        Deliberadamente devuelve el mismo `None` en ambos casos (tenant/usuario
        inexistente vs. contraseña incorrecta) para no revelar si una cuenta existe
        (mitigación estándar de enumeración de usuarios).
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, password_hash, password_salt, role_id, must_change_password, created_at "
            "FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE",
            (tenant_id, username.strip()),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        user_id, row_tenant_id, row_username, password_hash, salt, role_id, must_change_password, created_at = row
        is_valid = await asyncio.to_thread(_verify_password, password, salt, password_hash)
        if not is_valid:
            return None

        return User(
            id=user_id,
            tenant_id=row_tenant_id,
            username=row_username,
            role_id=role_id,
            must_change_password=bool(must_change_password),
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
        """Resuelve sesión + rol en una sola consulta (revisión 9).

        Usada por `AuthMiddleware` en lugar de `get_session()` + una consulta
        aparte de rol: evita una segunda ida a `auth.db` por petición solo para
        saber si el usuario es admin y qué proyectos puede ver.
        """
        cursor = await self._connection.execute(
            "SELECT s.token, s.user_id, s.tenant_id, s.created_at, s.expires_at, "
            "u.role_id, u.must_change_password, r.is_admin "
            "FROM sessions s JOIN users u ON s.user_id = u.id JOIN roles r ON u.role_id = r.id "
            "WHERE s.token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        token_value, user_id, tenant_id, created_at, expires_at, role_id, must_change_password, is_admin = row
        session = Session(token=token_value, user_id=user_id, tenant_id=tenant_id, created_at=created_at, expires_at=expires_at)
        if datetime.fromisoformat(session.expires_at) <= datetime.now(UTC):
            return None

        return AuthenticatedSession(session=session, role_id=role_id, is_admin=bool(is_admin), must_change_password=bool(must_change_password))

    async def delete_session(self, token: str) -> None:
        """Logout selectivo: borra solo la sesión de `token`.

        No afecta a otras sesiones del mismo usuario ni de ningún otro — es la
        propiedad explícitamente pedida por el usuario para `§2.7.2`.
        """
        await self._connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await self._connection.commit()


__all__ = ["AuthStore", "AuthenticatedSession"]
