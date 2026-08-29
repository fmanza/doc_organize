"""
Autenticación de la interfaz web: sesión multi-usuario y multi-tenant (revisión 8, §2.7.2).

Reemplaza el bearer token compartido de la revisión 2/7 (§2.7.1, ❌ SUPERSEDIDO): si el
host de bind no es loopback, TODA ruta —páginas HTML incluidas, no solo `/api/*` y
`/downloads/*`— exige una sesión válida (cookie `doc_organize_session`, obtenida vía
`POST /login` con usuario+contraseña+tenant). `/login` y `/logout` quedan exentos (si
no, nadie podría autenticarse nunca). Las escrituras además validan que
`Origin`/`Referer` coincidan con el `Host` de la propia petición (capa adicional a
`SameSite=Strict`, no CSRF-token clásico).
"""

import time

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from doc_organize.auth import AuthenticatedSession, AuthStore
from doc_organize.core.constants import LOGIN_LOCKOUT_SECONDS, LOGIN_MAX_ATTEMPTS
from doc_organize.core.models import SecurityConfig

SESSION_COOKIE_NAME = "doc_organize_session"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PROTECTED_PREFIXES = ("/api/", "/downloads/")
_EXEMPT_PATHS = frozenset({"/login", "/logout"})
#: Ruta alcanzable aunque `must_change_password=True` (revisión 9) — sin esta
#: excepción, un usuario con contraseña pendiente de cambio quedaría atrapado sin
#: poder llegar a la propia página que se lo permite. `/logout` no hace falta
#: aquí: ya sale por `_EXEMPT_PATHS` antes de llegar a esta comprobación.
_PASSWORD_CHANGE_EXEMPT = frozenset({"/change-password"})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_loopback(host: str) -> bool:
    """`True` si `host` es una dirección de loopback (no requiere autenticación)."""
    return host in _LOOPBACK_HOSTS


def requires_auth(security: SecurityConfig) -> bool:
    """`True` si `security` exige sesión válida (host no-loopback, auth habilitada)."""
    return security.require_auth_if_not_loopback and not is_loopback(security.bind_host)


async def authenticate_session(cookies: Mapping[str, str], auth_db_path: str | Path | None) -> AuthenticatedSession | None:
    """Resuelve la cookie de sesión (+ rol) contra `AuthStore`, o `None` si falta/no es válida.

    Compartida entre `AuthMiddleware` (rutas HTTP) y `web/routes/scan.py` (WebSocket,
    Fase D-2b, §2.7.3): `starlette.middleware.base.BaseHTTPMiddleware` **no** intercepta
    conexiones WebSocket (Starlette pasa el scope `"websocket"` directo a la app interna
    sin llamar a `dispatch()`), así que un handler WS debe autenticar la sesión a mano,
    llamando a esta misma función — nunca reimplementar la lógica. Devuelve
    `AuthenticatedSession` (no `Session`) desde la revisión 9: incluye `role_id`/
    `is_admin`/`must_change_password` resueltos en la misma consulta.
    """
    token = cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    store = AuthStore(auth_db_path) if auth_db_path else AuthStore()
    async with store as opened_store:
        return await opened_store.get_session_with_access(token)


class LoginRateLimiter:
    """Bloqueo temporal de `POST /login` tras demasiados fallos consecutivos para el
    mismo (tenant_id, username) (revisión de seguridad, revisión 9).

    Mitiga la adivinación del admin/admin de bootstrap (`DEFAULT_ADMIN_USERNAME`/
    `DEFAULT_ADMIN_PASSWORD`) antes de que el admin legítimo complete su primer
    login. En memoria del proceso — un reinicio del servidor limpia los contadores,
    aceptable: no es un mecanismo de auditoría, solo de frenado.

    Attributes:
        max_attempts (int): Fallos consecutivos antes de bloquear.
        lockout_seconds (float): Duración del bloqueo tras alcanzar `max_attempts`.

    Example:
        >>> limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=30)
        >>> limiter.is_locked("acme-corp", "admin")
        False
        >>> for _ in range(3): limiter.record_failure("acme-corp", "admin")
        >>> limiter.is_locked("acme-corp", "admin")
        True
    """

    def __init__(self, max_attempts: int = LOGIN_MAX_ATTEMPTS, lockout_seconds: float = LOGIN_LOCKOUT_SECONDS) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        #: key -> (count, locked_until_monotonic, last_failure_monotonic)
        self._failures: dict[str, tuple[int, float, float]] = {}

    @staticmethod
    def _key(tenant_id: str, username: str) -> str:
        return f"{tenant_id}:{username.strip().lower()}"

    def is_locked(self, tenant_id: str, username: str) -> bool:
        """`True` si (`tenant_id`, `username`) sigue dentro de su ventana de bloqueo."""
        key = self._key(tenant_id, username)
        entry = self._failures.get(key)
        if entry is None:
            return False
        count, locked_until, _ = entry
        if count < self.max_attempts:
            return False
        if time.monotonic() >= locked_until:
            del self._failures[key]  # ventana expirada: libera el contador
            return False
        return True

    def record_failure(self, tenant_id: str, username: str) -> None:
        """Cuenta un intento fallido; bloquea `lockout_seconds` al llegar a `max_attempts`."""
        now = time.monotonic()
        self._prune_stale(now)
        key = self._key(tenant_id, username)
        count = self._failures.get(key, (0, 0.0, 0.0))[0] + 1
        locked_until = now + self.lockout_seconds if count >= self.max_attempts else 0.0
        self._failures[key] = (count, locked_until, now)

    def record_success(self, tenant_id: str, username: str) -> None:
        """Limpia el contador de fallos tras un login correcto."""
        self._failures.pop(self._key(tenant_id, username), None)

    def _prune_stale(self, now: float) -> None:
        """Purga entradas sin fallos nuevos desde hace más de `lockout_seconds`.

        Sin esto, un fallo aislado (por debajo de `max_attempts`, nunca bloqueado)
        para un username que no vuelve a intentar login queda en memoria para
        siempre — `is_locked()` solo libera memoria de forma perezosa cuando
        alguien vuelve a consultar esa misma clave. `lockout_seconds` es también
        la ventana de retención correcta para las entradas ya bloqueadas: cuando
        ha pasado ese tiempo desde el último fallo, cualquier bloqueo activo ya
        habría expirado igualmente.
        """
        stale_keys = [key for key, (_, _, last_failure) in self._failures.items() if now - last_failure > self.lockout_seconds]
        for key in stale_keys:
            del self._failures[key]


class AuthMiddleware(BaseHTTPMiddleware):
    """Exige una sesión válida en toda ruta (páginas incluidas) cuando el servidor
    no está escuchando solo en loopback.

    Attributes:
        security (SecurityConfig): Configuración de host/puerto.
        auth_db_path (str | Path | None): Ruta alternativa a `auth.db` (uso en
            tests); si es `None`, `AuthStore` usa su ruta por defecto
            (`~/.doc_organize/auth.db`).
    """

    def __init__(self, app: object, security: SecurityConfig, auth_db_path: str | Path | None = None) -> None:
        # `app` se tipa como `object` (no el ASGIApp de Starlette) porque FastAPI
        # invoca `add_middleware(AuthMiddleware, ...)` con su propio wrapper interno;
        # BaseHTTPMiddleware.__init__ exige un tipo mas preciso, de ahi el ignore.
        super().__init__(app)  # type: ignore[arg-type]
        self.security = security
        self.auth_db_path = auth_db_path

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not requires_auth(self.security) or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        authenticated = await authenticate_session(request.cookies, self.auth_db_path)
        if authenticated is None:
            if request.url.path.startswith(_PROTECTED_PREFIXES):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return RedirectResponse("/login", status_code=303)

        request.state.user_id = authenticated.session.user_id
        request.state.tenant_id = authenticated.session.tenant_id
        request.state.role_id = authenticated.role_id
        request.state.is_admin = authenticated.is_admin

        if authenticated.must_change_password and request.url.path not in _PASSWORD_CHANGE_EXEMPT:
            if request.url.path.startswith(_PROTECTED_PREFIXES):
                return JSONResponse(status_code=403, content={"detail": "Password change required"})
            return RedirectResponse("/change-password", status_code=303)

        if request.method in _WRITE_METHODS:
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin is not None and not self._origin_matches_request_host(request, origin):
                return JSONResponse(status_code=403, content={"detail": "Forbidden: Origin mismatch"})

        return await call_next(request)

    @staticmethod
    def _origin_matches_request_host(request: Request, origin: str) -> bool:
        origin_netloc = urlparse(origin).netloc
        request_host = request.headers.get("host", "")
        return origin_netloc == request_host


__all__ = [
    "SESSION_COOKIE_NAME",
    "AuthMiddleware",
    "LoginRateLimiter",
    "authenticate_session",
    "is_loopback",
    "requires_auth",
]
