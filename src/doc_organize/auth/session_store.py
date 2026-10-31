"""
Sesiones de autenticación, separadas de `AuthStore` (`/tech-debt`, sesión 2026-09-17):
antes un único `AuthStore` de ~1050 líneas mezclaba tenants, roles, usuarios y sesiones
en una sola clase -- ver `auth/auth_store.py` (fachada que delega aquí) para el
contexto completo de la separación.

Comparte la conexión SQLite de `AuthStore` con el resto de stores -- ver el porqué en
la docstring de `tenant_store.py`.
"""

import logging
import secrets

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiosqlite

from doc_organize.core.constants import SESSION_LIFETIME_HOURS
from doc_organize.core.models import Session, User


@dataclass
class AuthenticatedSession:
    """Sesión + acceso resueltos en una sola consulta (revisión 9).

    Evita que `AuthMiddleware` tenga que hacer una segunda consulta a `auth.db` por
    petición solo para saber si el usuario de la sesión es admin y qué rol tiene —
    ver `SessionStore.get_session_with_access()`.
    """

    session: Session
    role_id: str
    is_admin: bool
    must_change_password: bool
    is_instance_admin: bool


class SessionStore:
    """Crear/consultar/revocar sesiones de autenticación.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self, connection: aiosqlite.Connection, *, logger: logging.Logger) -> None:
        self._connection = connection
        self.logger = logger

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

        JOIN de 3 tablas (sessions+users+roles) vía la conexión propia de
        `SessionStore`: válido aunque `UserStore`/`RoleStore` tengan sus propias
        conexiones -- todas apuntan al mismo fichero `auth.db`, SQLite no exige
        que una consulta use "la" conexión de cada tabla que toca.
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


__all__ = ["AuthenticatedSession", "SessionStore"]
