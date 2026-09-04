"""
Dependencias compartidas de las rutas web (REQ-007, revisión 9 roles y gestión de usuarios).
"""

from typing import cast

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from doc_organize.auth import AuthStore
from doc_organize.projects import ProjectRegistry, ScannedFoldersStore

# `HTTPConnection` (no `Request`): base compartida de `Request` y `WebSocket` en
# Starlette. Estas funciones solo tocan `.app.state`/`.state`, presentes en ambas —
# así sirven igual para las rutas HTTP normales y para el handler WebSocket de
# `web/routes/scan.py` (Fase D-2b, §2.7.3).


def get_project_registry(conn: HTTPConnection) -> ProjectRegistry:
    """Devuelve la instancia de `ProjectRegistry` compartida por esta app.

    Instancia única, creada una vez en `create_app()` (`app.state.project_registry`)
    — NO una nueva por conexión: su `asyncio.Lock` interno solo protege
    escrituras concurrentes a `projects.json` si todas las peticiones lo
    comparten (AUDIT_CODE, sesión 2026-09-03). Los tests inyectan una ruta de
    registro alternativa vía `create_app(registry_path=...)`, igual que
    `main.py::_registry()` hace para el CLI — así ninguno de los dos toca
    `~/.doc_organize/projects.json` en tests.
    """
    # `app.state` es un simple namespace dinámico (Starlette `State`), sin tipo
    # estático -- `cast` documenta el contrato real: `create_app()` siempre fija
    # `project_registry` antes de servir ninguna petición.
    return cast(ProjectRegistry, conn.app.state.project_registry)


def get_auth_store(conn: HTTPConnection) -> AuthStore:
    """Devuelve un `AuthStore` para esta conexión (revisión 8, §2.7.2).

    Mismo patrón que `get_project_registry`: permite inyectar una ruta alternativa
    a `auth.db` vía `app.state.auth_db_path` para no tocar `~/.doc_organize/auth.db`
    en tests.
    """
    auth_db_path = getattr(conn.app.state, "auth_db_path", None)
    return AuthStore(auth_db_path) if auth_db_path else AuthStore()


#: Instancia única de proceso: a diferencia de `ProjectRegistry`/`AuthStore`,
#: `ScannedFoldersStore` no tiene ningún parámetro de configuración por app (cada
#: método recibe el `Project` sobre el que opera, la ruta se deriva de
#: `project.root_path`) — un singleton de módulo basta para que su
#: `asyncio.Lock` interno sirva de algo entre peticiones concurrentes (AUDIT_CODE,
#: sesión 2026-09-03 — antes cada petición creaba su propia instancia con su
#: propio lock inútil, mismo bug que `ProjectRegistry`).
_scanned_folders_store = ScannedFoldersStore()


def get_scanned_folders_store() -> ScannedFoldersStore:
    """Devuelve la instancia de `ScannedFoldersStore` compartida por este proceso."""
    return _scanned_folders_store


def project_operation_key(tenant_id: str, project_name: str) -> tuple[str, str]:
    """Clave case-insensitive (mismo criterio que `ProjectRegistry.get_project`)
    para identificar un proyecto en `app.state.active_project_operations`.

    Compartida entre `web/routes/scan.py` (escaneo/deduplicación, vía WebSocket) y
    `web/routes/projects.py` (operaciones de mantenimiento, vía HTTP) — ambos leen y
    escriben el mismo `app.state.active_project_operations`, así que deben coincidir
    exactamente para que se bloqueen mutuamente sobre el mismo proyecto.
    """
    return (tenant_id, project_name.lower())


def get_tenant_id(conn: HTTPConnection) -> str:
    """Resuelve el tenant de esta conexión (revisión 8, §2.7.2).

    `AuthMiddleware` solo fija `request.state.tenant_id` cuando exige sesión (host
    no-loopback); en loopback/sin auth no hay sesión que resolver, así que se usa
    el tenant implícito `"default"` — el mismo que usa el CLI. Nunca se lee de un
    parámetro de query/body: el cliente no puede elegir en qué tenant opera. El
    handler WebSocket de `web/routes/scan.py` resuelve el tenant aparte (no pasa
    por `AuthMiddleware`, que no cubre WebSocket) y no usa esta función.
    """
    return getattr(conn.state, "tenant_id", "default")


def require_admin(request: Request) -> None:
    """Bloquea la ruta si la sesión activa no tiene un rol `is_admin` (revisión 9).

    En loopback/sin auth no hay sesión que resolver (mismo criterio que
    `get_tenant_id`): no se aplica ninguna restricción, igual que hoy no la hay
    para nada del resto de la app en ese modo.
    """
    is_admin = getattr(request.state, "is_admin", None)
    if is_admin is None:
        return
    if not is_admin:
        raise HTTPException(status_code=403, detail="Esta operación requiere un rol admin.")


async def get_allowed_scan_roots(request: Request) -> list[str] | None:
    """Resuelve las raíces de escaneo permitidas para la sesión de `request`, o `None` si no hay restricción.

    Equivalente HTTP de la comprobación que `scan.py::_authorize_project_websocket`
    hace a mano para los WebSocket de escaneo/deduplicación (`BaseHTTPMiddleware`
    no cubre WebSocket, así que ese handler no puede depender de
    `AuthMiddleware`/`request.state`). Usado
    por los endpoints REST del explorador de carpetas y de la lista persistente
    de carpetas (`web/routes/filesystem.py`, `web/routes/scan.py`), que sí pasan
    por `AuthMiddleware` y ya tienen `request.state.is_admin`/`role_id` resueltos.

    `None` (sin restricción) para: sesión no resuelta (loopback/sin auth, mismo
    criterio que `get_tenant_id`) o rol `is_admin`. Una lista (posiblemente
    vacía) para un rol restringido, tomada de `Role.allowed_scan_roots`.
    """
    is_admin = getattr(request.state, "is_admin", None)
    if is_admin is None or is_admin:
        return None

    role_id = request.state.role_id
    tenant_id = get_tenant_id(request)
    async with get_auth_store(request) as store:
        role = await store.get_role(tenant_id, role_id)
    return role.allowed_scan_roots


async def require_project_access(name: str, request: Request) -> None:
    """Bloquea el acceso a un proyecto si el rol de la sesión no lo permite (revisión 9).

    `name` se resuelve automáticamente del path param del endpoint que declare esta
    dependencia. Un rol `is_admin` accede a cualquier proyecto del tenant; un rol
    restringido solo a los de su lista. `404` (no `403`) en ambos casos de "no
    acceso", igual que "proyecto inexistente" — no revela si el proyecto existe
    fuera del alcance del usuario (mismo criterio de no-enumeración que
    `ProjectRegistry.get_project()`).
    """
    is_admin = getattr(request.state, "is_admin", None)
    if is_admin is None:  # sin sesión resuelta (loopback/no-auth): sin restricciones
        return
    if is_admin:
        return

    role_id = request.state.role_id
    tenant_id = get_tenant_id(request)
    async with get_auth_store(request) as store:
        allowed = await store.can_access_project(tenant_id, role_id, name)
    if not allowed:
        raise HTTPException(status_code=404, detail=f"No existe ningún proyecto llamado '{name}'.")


__all__ = [
    "get_allowed_scan_roots",
    "get_auth_store",
    "get_project_registry",
    "get_tenant_id",
    "project_operation_key",
    "require_admin",
    "require_project_access",
]
