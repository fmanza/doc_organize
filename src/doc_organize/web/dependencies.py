"""
Dependencias compartidas de las rutas web (REQ-007).
"""

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


__all__ = ["get_project_registry", "get_auth_store", "get_tenant_id"]
