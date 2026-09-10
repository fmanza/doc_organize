"""
Dependencias compartidas de las rutas web (REQ-007, revisión 9 roles y gestión de usuarios).
"""

from typing import cast

from fastapi import HTTPException, Request, WebSocket
from starlette.requests import HTTPConnection

from doc_organize.auth import AuthStore, InstanceSecretsStore
from doc_organize.context import TaxonomyTemplateRegistry
from doc_organize.core.exceptions import ProjectNotFoundError
from doc_organize.core.models import Project
from doc_organize.projects import ProjectRegistry, ScannedFoldersStore
from doc_organize.web.auth import authenticate_session, requires_auth

#: Motivo de cierre WebSocket cuando el proyecto no existe (o el rol no tiene
#: acceso, ver `authorize_project_websocket`) — compartido con `resolve_ws_project()`
#: para que ambos casos cierren con exactamente el mismo texto.
_WS_REASON_PROJECT_NOT_FOUND = "Project not found"

# `HTTPConnection` (no `Request`): base compartida de `Request` y `WebSocket` en
# Starlette. Estas funciones solo tocan `.app.state`/`.state`, presentes en ambas —
# así sirven igual para las rutas HTTP normales y para los handlers WebSocket de
# `web/routes/scan.py` (Fase D-2b, §2.7.3) y `web/routes/context.py`.


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


def get_instance_secrets_store(conn: HTTPConnection) -> InstanceSecretsStore:
    """Devuelve un `InstanceSecretsStore` para esta conexión (panel de configuración IA).

    Mismo patrón que `get_auth_store`: comparte el mismo fichero `auth.db` (y el
    mismo `app.state.auth_db_path` inyectable en tests) pero con su propia tabla y
    ciclo de vida de conexión -- SRP, igual criterio que separa las distintas
    `LiteLLM*Config` aunque compartan infraestructura (ver `AUDIT_PLAN` de la sesión
    que añadió este módulo).
    """
    auth_db_path = getattr(conn.app.state, "auth_db_path", None)
    return InstanceSecretsStore(auth_db_path) if auth_db_path else InstanceSecretsStore()


def get_taxonomy_template_registry(conn: HTTPConnection) -> TaxonomyTemplateRegistry:
    """Devuelve la instancia de `TaxonomyTemplateRegistry` compartida por esta app.

    Mismo patrón que `get_project_registry`: instancia única creada en `create_app()`
    (`app.state.taxonomy_template_registry`), con una ruta de biblioteca alternativa
    inyectable en tests (`create_app(templates_path=...)`, igual que `main.py::_run_web()`
    hace para el CLI vía `--templates-path`) para no tocar
    `~/.doc_organize/taxonomy_templates/` real. A diferencia de `ProjectRegistry`/
    `AuthStore`, esta clase no escribe nada (solo lee plantillas de disco), así que no
    necesita compartir ningún lock — la instancia única es solo para no repetir la
    resolución de ruta en cada petición.
    """
    return cast(TaxonomyTemplateRegistry, conn.app.state.taxonomy_template_registry)


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


async def authorize_project_websocket(websocket: WebSocket, project_name: str) -> tuple[str, list[str] | None] | None:
    """Autentica (si aplica) y resuelve `tenant_id` + `allowed_scan_roots` para una
    conexión WebSocket sobre un proyecto.

    Compartida por los WebSocket de `web/routes/scan.py` (escaneo/deduplicación) y
    `web/routes/context.py` (construir/eliminar contexto) — antes cada fichero
    mantenía su propia copia de esta lógica de autenticación/autorización; unificada
    aquí para que una corrección de seguridad futura no dependa de recordar
    replicarla en el otro sitio (AUDIT_CODE, sesión 2026-09-10).

    Autenticación manual (Fase D-2b, §2.7.3): `AuthMiddleware` extiende
    `BaseHTTPMiddleware`, que **no** intercepta conexiones WebSocket — Starlette pasa
    el scope `"websocket"` directo a la app interna sin llamar a `dispatch()`. Sin
    esta comprobación explícita, estas rutas quedarían accesibles sin sesión aunque
    el resto de la app la exija en modo no-loopback.

    Devuelve `None` si ya se cerró el websocket (sin sesión válida, o sin acceso al
    proyecto) — el llamador no debe hacer nada más. `allowed_scan_roots` es `None`
    cuando no hay restricción de rutas (admin o loopback/sin auth); una lista
    (posiblemente vacía) restringe los `paths` aceptados a esas raíces — los
    llamadores que no aceptan rutas de filesystem del cliente (p.ej.
    `web/routes/context.py`) simplemente ignoran ese segundo valor.
    """
    security = websocket.app.state.security
    auth_db_path = getattr(websocket.app.state, "auth_db_path", None)

    if not requires_auth(security):
        return "default", None

    authenticated = await authenticate_session(websocket.cookies, auth_db_path)
    if authenticated is None:
        await websocket.close(code=1008, reason="Unauthorized")
        return None

    tenant_id = authenticated.session.tenant_id
    if authenticated.is_admin:
        return tenant_id, None

    async with get_auth_store(websocket) as store:
        allowed = await store.can_access_project(tenant_id, authenticated.role_id, project_name)
        if not allowed:
            await websocket.close(code=1008, reason=_WS_REASON_PROJECT_NOT_FOUND)
            return None
        role = await store.get_role(tenant_id, authenticated.role_id)
        return tenant_id, role.allowed_scan_roots


async def resolve_ws_project(websocket: WebSocket, registry: ProjectRegistry, name: str, tenant_id: str) -> Project | None:
    """Resuelve el proyecto `name` para una conexión WebSocket ya autorizada, cerrando
    con 1008 si no existe.

    Compartida por los 4 WebSocket de `web/routes/scan.py` (escaneo/deduplicación) y
    `web/routes/context.py` (construir/eliminar contexto) — cada uno repetía el mismo
    `try/except ProjectNotFoundError` alrededor de `ProjectRegistry.get_project()` con
    idéntico texto de cierre; unificada aquí junto con `authorize_project_websocket()`/
    `acquire_project_operation_lock()` (AUDIT_CODE, sesión 2026-09-10).

    Devuelve `None` si ya se cerró el websocket — el llamador no debe hacer nada más.
    """
    try:
        return await registry.get_project(name, tenant_id=tenant_id)
    except ProjectNotFoundError:
        await websocket.close(code=1008, reason=_WS_REASON_PROJECT_NOT_FOUND)
        return None


def project_operation_key(tenant_id: str, project_name: str) -> tuple[str, str]:
    """Clave case-insensitive (mismo criterio que `ProjectRegistry.get_project`)
    para identificar un proyecto en `app.state.active_project_operations`.

    Usada por `acquire_project_operation_lock()` (WebSocket, más abajo en este mismo
    fichero) y, duplicada por valor de retorno idéntico, por los locks HTTP de
    `web/routes/projects.py` y `web/routes/context.py` (operaciones de mantenimiento
    y de contexto) — todos leen y escriben el mismo `app.state.active_project_operations`,
    así que deben coincidir exactamente para que se bloqueen mutuamente sobre el
    mismo proyecto sea cual sea el transporte (HTTP o WebSocket).
    """
    return (tenant_id, project_name.lower())


async def acquire_project_operation_lock(websocket: WebSocket, tenant_id: str, project_name: str) -> tuple[str, str] | None:
    """Reserva `(tenant_id, project_name)` para esta conexión WebSocket, o cierra
    con 1008 si ya hay una operación en curso para ese proyecto.

    Compartida por los WebSocket de `web/routes/scan.py` (escaneo/deduplicación) y
    `web/routes/context.py` (construir/eliminar contexto) — todos leen/escriben el
    mismo `app.state.active_project_operations` vía la misma `project_operation_key()`,
    así que se bloquean mutuamente entre sí y con las operaciones equivalentes por
    HTTP (`_acquire_operation_lock`, duplicado en cada fichero de rutas HTTP — ver
    su propio docstring sobre por qué ESE sí sigue duplicado). Antes cada WebSocket
    mantenía su propia copia de esta función, con un texto de error ligeramente
    distinto entre sí ("Ya hay un escaneo o deduplicación..." en `scan.py` frente a
    "...u otra operación..." en `context.py`, que coincidía con el texto ya usado en
    los 409 HTTP) — unificada aquí junto con `authorize_project_websocket()`
    (AUDIT_CODE, sesión 2026-09-10).

    Devuelve la clave reservada (para liberarla después con
    `release_project_operation_lock()`), o `None` si ya había una operación en curso
    para ese proyecto (y ya cerró el websocket con 1008 — el llamador no debe hacer
    nada más).
    """
    key = project_operation_key(tenant_id, project_name)
    active = websocket.app.state.active_project_operations
    if key in active:
        await websocket.close(code=1008, reason="Ya hay un escaneo, deduplicación u otra operación en curso para este proyecto")
        return None
    active.add(key)
    return key


def release_project_operation_lock(websocket: WebSocket, key: tuple[str, str]) -> None:
    websocket.app.state.active_project_operations.discard(key)


def get_tenant_id(conn: HTTPConnection) -> str:
    """Resuelve el tenant de esta conexión (revisión 8, §2.7.2).

    `AuthMiddleware` solo fija `request.state.tenant_id` cuando exige sesión (host
    no-loopback); en loopback/sin auth no hay sesión que resolver, así que se usa
    el tenant implícito `"default"` — el mismo que usa el CLI. Nunca se lee de un
    parámetro de query/body: el cliente no puede elegir en qué tenant opera. Los
    handlers WebSocket (`web/routes/scan.py`, `web/routes/context.py`) resuelven el
    tenant aparte, vía `authorize_project_websocket()` (no pasan por `AuthMiddleware`,
    que no cubre WebSocket) y no usan esta función.
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

    Equivalente HTTP de la comprobación que `authorize_project_websocket()` hace a
    mano para los WebSocket de escaneo/deduplicación/contexto (`BaseHTTPMiddleware`
    no cubre WebSocket, así que esos handlers no pueden depender de
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
        raise HTTPException(status_code=404, detail=str(ProjectNotFoundError(name)))


__all__ = [
    "acquire_project_operation_lock",
    "authorize_project_websocket",
    "get_allowed_scan_roots",
    "get_auth_store",
    "get_instance_secrets_store",
    "get_project_registry",
    "get_taxonomy_template_registry",
    "get_tenant_id",
    "project_operation_key",
    "release_project_operation_lock",
    "require_admin",
    "require_project_access",
    "resolve_ws_project",
]
