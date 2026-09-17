"""
Tenants de autenticación, separados de `AuthStore` (`/tech-debt`, sesión 2026-09-17) --
ver `auth/auth_store.py` (fachada que delega aquí) para el contexto completo de la
separación en `TenantStore`/`RoleStore`/`UserStore`/`SessionStore`.

Comparte la conexión SQLite de `AuthStore` (inyectada en el constructor) con el resto
de stores -- no abre la suya propia: `AuthStore` no es un singleton de vida larga en
esta app (se instancia una vez por petición, ver `web/dependencies.py::get_auth_store`
y `web/auth.py::authenticate_session`, en el camino de cada request autenticada), así
que 4 conexiones independientes multiplicarían por 4 el coste de abrir/cerrar conexión
en el hot path de toda la aplicación (AUDIT_CODE, sesión 2026-09-17). La separación en
4 clases es por responsabilidad (SRP), no por aislamiento de conexión.
"""

import logging
import re
import unicodedata

import aiosqlite

from doc_organize.core.constants import TENANT_ID_MAX_LENGTH
from doc_organize.core.exceptions import AuthError, TenantAlreadyExistsError, TenantInUseError, TenantNotFoundError
from doc_organize.core.models import Tenant

from ._security import now_iso

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SLUG_COLLAPSE_DASHES = re.compile(r"-+")


def _slugify(name: str) -> str:
    """Deriva un identificador de tenant (slug) a partir de un nombre legible."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = ascii_name.strip().lower().replace(" ", "-")
    slug = _SLUG_INVALID_CHARS.sub("-", slug)
    slug = _SLUG_COLLAPSE_DASHES.sub("-", slug)
    return slug.strip("-")


class TenantStore:
    """CRUD de tenants (multi-tenant, rediseño Tenant/Role/User).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self, connection: aiosqlite.Connection, *, logger: logging.Logger) -> None:
        self._connection = connection
        self.logger = logger

    async def create_tenant(self, name: str) -> Tenant:
        """Crea un tenant nuevo; su `id` se deriva de `name` (slug).

        A diferencia de la revisión 9, ya NO aprovisiona automáticamente un rol ni
        un usuario admin: `Role` ya no está ligado a un tenant (rediseño
        Tenant/Role/User), así que no hay "rol admin de ESTE tenant" que crear. El
        primer usuario de un tenant nuevo lo da de alta un `is_instance_admin`
        (pantalla "Tenants y usuarios") o `user create` por CLI, asignándole
        cualquier rol `is_admin=True` ya existente (o uno nuevo). Solo
        `DEFAULT_TENANT_ID` recibe bootstrap automático, vía
        `AuthStore._ensure_default_tenant_bootstrap()` en `__aenter__`, no este método.

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

        tenant = Tenant(id=slug, name=stripped, created_at=now_iso())
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
        except Exception as exc:
            # Rollback defensivo: cualquier otra excepción (OSError, etc.) aborta la transacción.
            # Registramos para debugging futuro (no es fatal, reintento en próxima apertura).
            await self._connection.rollback()
            self.logger.warning(f"Error inesperado al crear tenant '{slug}': {exc}", exc_info=True)
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

    async def delete_tenant(self, tenant_id: str, *, has_projects: bool, user_count: int) -> None:
        """Elimina un tenant. Solo si no tiene usuarios NI proyectos asociados.

        `has_projects`/`user_count` los resuelve el llamador (`AuthStore.delete_tenant`,
        vía `UserStore`/`ProjectRegistry`) — `TenantStore` no depende de `UserStore` ni de
        `projects.py` (mismo criterio DIP que el resto del módulo: la pertenencia de un
        proyecto a un tenant vive en `ProjectRegistry`, no aquí; y contar usuarios es
        responsabilidad de `UserStore`, no de `TenantStore`).

        `DEFAULT_TENANT_ID` no es un caso especial aquí: se puede eliminar igual
        que cualquier otro, y `_ensure_default_tenant_bootstrap()` lo recreará de
        fábrica (con un usuario admin nuevo) la próxima vez que se abra `AuthStore`.

        Raises:
            TenantNotFoundError: Si `tenant_id` no existe.
            TenantInUseError: Si tiene usuarios o proyectos asociados.
        """
        if not await self.tenant_exists(tenant_id):
            raise TenantNotFoundError(tenant_id)

        if user_count > 0:
            raise TenantInUseError(f"El tenant '{tenant_id}' tiene {user_count} usuario(s); elimínalos antes de borrar el tenant.")
        if has_projects:
            raise TenantInUseError(f"El tenant '{tenant_id}' tiene proyectos asociados; elimínalos antes de borrar el tenant.")

        await self._connection.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        await self._connection.commit()


__all__ = ["TenantStore"]
