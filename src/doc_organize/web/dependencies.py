"""
Dependencias compartidas de las rutas web (REQ-007, revisión 9 roles y gestión de usuarios).
"""

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from doc_organize.auth import AuthStore
from doc_organize.projects import ProjectRegistry

# `HTTPConnection` (no `Request`): base compartida de `Request` y `WebSocket` en
# Starlette. Estas funciones solo tocan `.app.state`/`.state`, presentes en ambas —
# así sirven igual para las rutas HTTP normales y para el handler WebSocket de
# `web/routes/scan.py` (Fase D-2b, §2.7.3).


def get_project_registry(conn: HTTPConnection) -> ProjectRegistry:
    """Devuelve un `ProjectRegistry` para esta conexión.

    Permite a los tests inyectar una ruta de registro alternativa vía
    `app.state.registry_path`, igual que `main.py::_registry()` hace para el CLI —
    así ninguno de los dos toca `~/.doc_organize/projects.json` en tests.
    """
    registry_path = getattr(conn.app.state, "registry_path", None)
    return ProjectRegistry(registry_path) if registry_path else ProjectRegistry()


def get_auth_store(conn: HTTPConnection) -> AuthStore:
    """Devuelve un `AuthStore` para esta conexión (revisión 8, §2.7.2).

    Mismo patrón que `get_project_registry`: permite inyectar una ruta alternativa
    a `auth.db` vía `app.state.auth_db_path` para no tocar `~/.doc_organize/auth.db`
    en tests.
    """
    auth_db_path = getattr(conn.app.state, "auth_db_path", None)
    return AuthStore(auth_db_path) if auth_db_path else AuthStore()


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


__all__ = ["get_project_registry", "get_auth_store", "get_tenant_id", "require_admin", "require_project_access"]
