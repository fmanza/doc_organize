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

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig, Session

SESSION_COOKIE_NAME = "doc_organize_session"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PROTECTED_PREFIXES = ("/api/", "/downloads/")
_EXEMPT_PATHS = frozenset({"/login", "/logout"})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_loopback(host: str) -> bool:
    """`True` si `host` es una dirección de loopback (no requiere autenticación)."""
    return host in _LOOPBACK_HOSTS


def requires_auth(security: SecurityConfig) -> bool:
    """`True` si `security` exige sesión válida (host no-loopback, auth habilitada)."""
    return security.require_auth_if_not_loopback and not is_loopback(security.bind_host)


async def authenticate_session(cookies: Mapping[str, str], auth_db_path: str | Path | None) -> Session | None:
    """Resuelve la cookie de sesión contra `AuthStore`, o `None` si falta/no es válida.

    Compartida entre `AuthMiddleware` (rutas HTTP) y `web/routes/scan.py` (WebSocket,
    Fase D-2b, §2.7.3): `starlette.middleware.base.BaseHTTPMiddleware` **no** intercepta
    conexiones WebSocket (Starlette pasa el scope `"websocket"` directo a la app interna
    sin llamar a `dispatch()`), así que un handler WS debe autenticar la sesión a mano,
    llamando a esta misma función — nunca reimplementar la lógica.
    """
    token = cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    store = AuthStore(auth_db_path) if auth_db_path else AuthStore()
    async with store as opened_store:
        return await opened_store.get_session(token)


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

        session = await authenticate_session(request.cookies, self.auth_db_path)
        if session is None:
            if request.url.path.startswith(_PROTECTED_PREFIXES):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return RedirectResponse("/login", status_code=303)

        request.state.user_id = session.user_id
        request.state.tenant_id = session.tenant_id

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


__all__ = ["AuthMiddleware", "SESSION_COOKIE_NAME", "authenticate_session", "is_loopback", "requires_auth"]
