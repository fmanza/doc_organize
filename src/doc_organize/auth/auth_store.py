"""
Almacen de tenants, usuarios y sesiones (SQLite + WAL) para autenticacion
multi-usuario y multi-tenant (revision 8, §2.7.2).
"""

import asyncio
import hashlib
import re
import secrets
import unicodedata

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import aiosqlite

from doc_organize.core.constants import (
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
    TenantAlreadyExistsError,
    TenantNotFoundError,
    UserAlreadyExistsError,
)
from doc_organize.core.models import Session, Tenant, User
from doc_organize.utils.logging import get_logger

_DEFAULT_AUTH_DB_PATH = Path.home() / ".doc_organize" / "auth.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
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
    return datetime.now(timezone.utc).isoformat()


class AuthStore:
    """Almacen de tenants, usuarios y sesiones para autenticacion multi-tenant.

    SQLite+WAL en `~/.doc_organize/auth.db`, no el patron JSON+asyncio.Lock de
    `ProjectRegistry`: a diferencia de `projects.json`, aqui hay relaciones reales
    entre tres entidades (tenant -> usuario -> sesion) que se benefician de FK real
    e integridad referencial — mismo argumento que ya justifico SQLite para
    `cache.db` (AUDIT_PLAN revision 1). Las contrasenas se hashean con
    `hashlib.scrypt` (parametros OWASP) + salt aleatorio por usuario; los tokens de
    sesion son opacos (`secrets.token_urlsafe`), nunca derivados de la contrasena.

    Attributes:
        db_path (Path): Ruta al archivo SQLite.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> async def main():
        ...     async with AuthStore("./auth.db") as store:
        ...         tenant = await store.create_tenant("Acme Corp")
        ...         user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        ...         authenticated = await store.authenticate(tenant.id, "alice", "s3cr3t-password")
        >>> asyncio.run(main())
    """

    def __init__(self, db_path: str | Path = _DEFAULT_AUTH_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.logger = get_logger(__name__)
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "AuthStore":
        await asyncio.to_thread(self.db_path.parent.mkdir, parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
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

    async def create_tenant(self, name: str) -> Tenant:
        """Crea un tenant nuevo; su `id` se deriva de `name` (slug).

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
            raise TenantAlreadyExistsError(f"Ya existe un tenant con id '{slug}'.")

        tenant = Tenant(id=slug, name=stripped, created_at=_now_iso())
        await self._connection.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
            (tenant.id, tenant.name, tenant.created_at),
        )
        await self._connection.commit()
        self.logger.info(f"Tenant creado: '{tenant.id}' ({tenant.name})")
        return tenant

    async def tenant_exists(self, tenant_id: str) -> bool:
        """True si hay un tenant registrado con ese `id` exacto."""
        cursor = await self._connection.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,))
        return await cursor.fetchone() is not None

    async def create_user(self, tenant_id: str, username: str, password: str) -> User:
        """Crea un usuario dentro de `tenant_id`; `username` es único por tenant (case-insensitive).

        Raises:
            AuthError: Si `username`/`password` no cumplen las reglas mínimas.
            TenantNotFoundError: Si `tenant_id` no existe.
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
            raise TenantNotFoundError(f"No existe ningún tenant con id '{tenant_id}'.")

        cursor = await self._connection.execute(
            "SELECT 1 FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE",
            (tenant_id, stripped_username),
        )
        if await cursor.fetchone() is not None:
            raise UserAlreadyExistsError(f"Ya existe un usuario '{stripped_username}' en el tenant '{tenant_id}'.")

        salt, password_hash = await asyncio.to_thread(_hash_password, password)
        user = User(id=str(uuid4()), tenant_id=tenant_id, username=stripped_username, created_at=_now_iso())
        await self._connection.execute(
            "INSERT INTO users (id, tenant_id, username, password_hash, password_salt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, user.tenant_id, user.username, password_hash, salt, user.created_at),
        )
        await self._connection.commit()
        self.logger.info(f"Usuario creado: '{user.username}' en tenant '{tenant_id}'")
        return user

    async def authenticate(self, tenant_id: str, username: str, password: str) -> User | None:
        """Valida credenciales; `None` si el tenant/usuario no existe o la contraseña no coincide.

        Deliberadamente devuelve el mismo `None` en ambos casos (tenant/usuario
        inexistente vs. contraseña incorrecta) para no revelar si una cuenta existe
        (mitigación estándar de enumeración de usuarios).
        """
        cursor = await self._connection.execute(
            "SELECT id, tenant_id, username, password_hash, password_salt, created_at "
            "FROM users WHERE tenant_id = ? AND username = ? COLLATE NOCASE",
            (tenant_id, username.strip()),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        user_id, row_tenant_id, row_username, password_hash, salt, created_at = row
        is_valid = await asyncio.to_thread(_verify_password, password, salt, password_hash)
        if not is_valid:
            return None

        return User(id=user_id, tenant_id=row_tenant_id, username=row_username, created_at=created_at)

    async def create_session(self, user: User) -> Session:
        """Crea una sesión nueva para `user`, con vida fija (`SESSION_LIFETIME_HOURS`)."""
        now = datetime.now(timezone.utc)
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
        if datetime.fromisoformat(session.expires_at) <= datetime.now(timezone.utc):
            return None
        return session

    async def delete_session(self, token: str) -> None:
        """Logout selectivo: borra solo la sesión de `token`.

        No afecta a otras sesiones del mismo usuario ni de ningún otro — es la
        propiedad explícitamente pedida por el usuario para `§2.7.2`.
        """
        await self._connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await self._connection.commit()


__all__ = ["AuthStore"]
