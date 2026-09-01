"""
Rutas de login/logout: sesión multi-usuario y multi-tenant (revisión 8, §2.7.2).
"""

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from doc_organize.core.constants import SESSION_LIFETIME_HOURS
from doc_organize.web.auth import SESSION_COOKIE_NAME, LoginRateLimiter
from doc_organize.web.dependencies import get_auth_store
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request, "login.html.j2", {"error": None})


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
            "login.html.j2",
            {"error": "Demasiados intentos fallidos. Inténtalo de nuevo en un minuto."},
            status_code=429,
        )

    async with get_auth_store(request) as store:
        user = await store.authenticate(tenant_id, username, password)
        if user is None:
            limiter.record_failure(tenant_id, username)
            return _templates.TemplateResponse(
                request,
                "login.html.j2",
                {"error": "Tenant, usuario o contraseña incorrectos."},
                status_code=401,
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
