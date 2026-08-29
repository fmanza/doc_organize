"""
Cambio de contraseña autoservicio (revisión 9): escape del bloqueo `must_change_password`.

Ruta exenta del bloqueo de `AuthMiddleware` para contraseña pendiente de cambio
(`_PASSWORD_CHANGE_EXEMPT`), pero no de la exigencia de sesión: sigue exigiendo
cookie de sesión válida como cualquier otra ruta no listada en `_EXEMPT_PATHS`.
"""

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from doc_organize.web.dependencies import get_auth_store

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(tags=["auth"])


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_form(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request, "change_password.html", {"error": None})


@router.post("/change-password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:  # loopback/sin auth: no hay sesión sobre la que cambiar nada
        return RedirectResponse("/", status_code=303)

    if new_password != confirm_password:
        return _templates.TemplateResponse(
            request, "change_password.html", {"error": "Las contraseñas nuevas no coinciden."}, status_code=422
        )

    async with get_auth_store(request) as store:
        success = await store.change_password(user_id, current_password, new_password)

    if not success:
        return _templates.TemplateResponse(
            request, "change_password.html", {"error": "La contraseña actual no es correcta."}, status_code=401
        )

    return RedirectResponse("/", status_code=303)


__all__ = ["router"]
