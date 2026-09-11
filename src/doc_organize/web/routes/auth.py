"""
Rutas de login/logout: sesión multi-usuario y multi-tenant (revisión 8, §2.7.2).
"""

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from doc_organize.auth import is_factory_admin_account
from doc_organize.core.constants import SESSION_LIFETIME_HOURS
from doc_organize.web.auth import SESSION_COOKIE_NAME, LoginRateLimiter, requires_auth
from doc_organize.web.dependencies import get_auth_store
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)
_LOGIN_TEMPLATE = "login.html.j2"

#: Mensaje mostrado cuando la cuenta de fábrica ('admin' del tenant por defecto)
#: intenta iniciar sesión en modo no-loopback con su contraseña todavía sin
#: cambiar (decisión de diseño 1, rediseño Tenant/Role/User): se rechaza el login
#: en sí -- no basta con redirigir tras entrar, `/change-password` ya exige una
#: sesión creada, así que permitir el login equivaldría a dejar tomar la cuenta a
#: quien conozca la contraseña de fábrica (pública, documentada).
_FACTORY_ADMIN_LOCKOUT_MESSAGE = (
    "La cuenta de fábrica 'admin' no puede iniciar sesión mientras el servidor esté expuesto "
    "(modo no-loopback) y su contraseña siga siendo la de fábrica. Arranca "
    "`python -m doc_organize web` sin --host (modo loopback), inicia sesión ahí y cambia la "
    "contraseña antes de volver a exponer el servidor."
)

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request, _LOGIN_TEMPLATE, {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    tenant_id: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    """Valida credenciales; en éxito fija la cookie de sesión y redirige a `/`.

    Mismo `401` + re-render tanto si el tenant/usuario no existe como si la
    contraseña es incorrecta — evita revelar cuál de los tres campos falló
    (mitigación de enumeración de usuarios, ya aplicada en `AuthStore.authenticate`).

    Bloqueada por `LoginRateLimiter` tras varios fallos consecutivos para el mismo
    (tenant_id, username) — mitiga la fuerza bruta sobre el admin/admin de bootstrap
    (revisión de seguridad, revisión 9).
    """
    tenant_id = tenant_id.strip()
    limiter: LoginRateLimiter = request.app.state.login_rate_limiter
    if limiter.is_locked(tenant_id, username):
        return _templates.TemplateResponse(
            request,
            _LOGIN_TEMPLATE,
            {"error": "Demasiados intentos fallidos. Inténtalo de nuevo en un minuto."},
            status_code=429,
        )

    async with get_auth_store(request) as store:
        user = await store.authenticate(tenant_id, username, password)
        if user is None:
            limiter.record_failure(tenant_id, username)
            return _templates.TemplateResponse(
                request,
                _LOGIN_TEMPLATE,
                {"error": "Tenant, usuario o contraseña incorrectos."},
                status_code=401,
            )

        # Decisión de diseño 1 (rediseño Tenant/Role/User): la contraseña era
        # correcta (no cuenta como fallo del limitador), pero es la cuenta de
        # fábrica sin rotar en un servidor expuesto -- se rechaza el login en sí,
        # ver `_FACTORY_ADMIN_LOCKOUT_MESSAGE`.
        if requires_auth(request.app.state.security) and is_factory_admin_account(user):
            return _templates.TemplateResponse(
                request,
                _LOGIN_TEMPLATE,
                {"error": _FACTORY_ADMIN_LOCKOUT_MESSAGE},
                status_code=403,
            )

        session = await store.create_session(user)

    limiter.record_success(tenant_id, username)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session.token,
        httponly=True,
        samesite="strict",
        # `secure=True` solo si la propia petición llegó por HTTPS: sobre HTTP puro
        # (loopback local, tests) el navegador/cliente descartaría una cookie Secure
        # y ningún request posterior la reenviaría. En un despliegue no-loopback
        # detrás de un proxy TLS, el proxy debe reenviar el esquema real (p. ej.
        # `X-Forwarded-Proto` + `ProxyHeadersMiddleware`) para que esta condición
        # se cumpla y la cookie de sesión no viaje nunca en claro.
        secure=request.url.scheme == "https",
        max_age=SESSION_LIFETIME_HOURS * 3600,
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Logout selectivo: borra solo la sesión de la cookie de esta petición."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        async with get_auth_store(request) as store:
            await store.delete_session(token)

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


__all__ = ["router"]
