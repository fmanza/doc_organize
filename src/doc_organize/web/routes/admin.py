"""
Gestión de roles y usuarios (revisión 9): CRUD admin-only sobre `AuthStore`.

Todas las rutas de este router exigen `require_admin` (declarado a nivel de
`APIRouter`, no por endpoint — imposible olvidarlo en una ruta nueva). En
loopback/sin auth no hay sesión que resolver, así que `require_admin` no aplica
ninguna restricción ahí (mismo criterio que el resto de la app).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from doc_organize.core.exceptions import RoleNotFoundError
from doc_organize.core.models import Role, User
from doc_organize.web.dependencies import get_auth_store, get_project_registry, get_tenant_id, require_admin
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


class RoleResponse(BaseModel):
    id: str
    name: str
    is_admin: bool
    project_names: list[str]
    allowed_scan_roots: list[str]
    created_at: str


class RoleListResponse(BaseModel):
    roles: list[RoleResponse]


class CreateRoleRequest(BaseModel):
    name: str
    is_admin: bool = False
    project_names: list[str] = []
    allowed_scan_roots: list[str] = []


class UpdateRoleRequest(BaseModel):
    name: str | None = None
    is_admin: bool | None = None
    project_names: list[str] | None = None
    allowed_scan_roots: list[str] | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    role_id: str
    must_change_password: bool
    created_at: str


class UserListResponse(BaseModel):
    users: list[UserResponse]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role_id: str


class UpdateUserRequest(BaseModel):
    role_id: str | None = None
    password: str | None = None


def _role_response(role: Role) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        name=role.name,
        is_admin=role.is_admin,
        project_names=role.project_names,
        allowed_scan_roots=role.allowed_scan_roots,
        created_at=role.created_at,
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role_id=user.role_id,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request) -> HTMLResponse:
    tenant_id = get_tenant_id(request)
    async with get_auth_store(request) as store:
        users = await store.list_users(tenant_id)
        roles = await store.list_roles(tenant_id)
    async with get_project_registry(request) as registry:
        projects = await registry.list_projects(tenant_id=tenant_id)
    roles_by_id = {role.id: role for role in roles}
    return _templates.TemplateResponse(
        request,
        "admin_users.html.j2",
        {"users": users, "roles": roles, "roles_by_id": roles_by_id, "projects": projects},
    )


@router.get("/api/roles", response_model=RoleListResponse)
async def list_roles(request: Request) -> RoleListResponse:
    async with get_auth_store(request) as store:
        roles = await store.list_roles(get_tenant_id(request))
    return RoleListResponse(roles=[_role_response(role) for role in roles])


@router.post("/api/roles", response_model=RoleResponse, status_code=201)
async def create_role(payload: CreateRoleRequest, request: Request) -> RoleResponse:
    # RoleAlreadyExistsError/AuthError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 409/422.
    async with get_auth_store(request) as store:
        role = await store.create_role(
            get_tenant_id(request),
            payload.name,
            is_admin=payload.is_admin,
            project_names=payload.project_names,
            allowed_scan_roots=payload.allowed_scan_roots,
        )
    return _role_response(role)


@router.get("/api/roles/{role_id}", response_model=RoleResponse)
async def get_role(role_id: str, request: Request) -> RoleResponse:
    # RoleNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_auth_store(request) as store:
        role = await store.get_role(get_tenant_id(request), role_id)
    return _role_response(role)


@router.patch("/api/roles/{role_id}", response_model=RoleResponse)
async def update_role(role_id: str, payload: UpdateRoleRequest, request: Request) -> RoleResponse:
    # RoleNotFoundError/RoleAlreadyExistsError/AuthError se propagan sin
    # capturar: el handler global de web/app.py (_EXCEPTION_STATUS_CODES)
    # las traduce a 404/409/422 respectivamente.
    async with get_auth_store(request) as store:
        role = await store.update_role(
            get_tenant_id(request),
            role_id,
            name=payload.name,
            is_admin=payload.is_admin,
            project_names=payload.project_names,
            allowed_scan_roots=payload.allowed_scan_roots,
        )
    return _role_response(role)


@router.delete("/api/roles/{role_id}", status_code=204)
async def delete_role(role_id: str, request: Request) -> None:
    # RoleNotFoundError/RoleInUseError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 404/409.
    async with get_auth_store(request) as store:
        await store.delete_role(get_tenant_id(request), role_id)


@router.get("/api/users", response_model=UserListResponse)
async def list_users(request: Request) -> UserListResponse:
    async with get_auth_store(request) as store:
        users = await store.list_users(get_tenant_id(request))
    return UserListResponse(users=[_user_response(user) for user in users])


@router.post("/api/users", response_model=UserResponse, status_code=201)
async def create_user(payload: CreateUserRequest, request: Request) -> UserResponse:
    """Crea un usuario.

    `RoleNotFoundError` se captura explícitamente aquí (a diferencia de las demás
    rutas de este router): el handler global de `web/app.py` la traduce a 404 —
    correcto cuando el rol es el recurso direccionado por la URL (`/api/roles/{id}`),
    pero engañoso aquí, donde `role_id` es solo una referencia dentro del payload
    de un usuario y un 422 (entrada inválida) describe mejor el fallo.
    `UserAlreadyExistsError`/`AuthError` sí se propagan sin capturar: el handler
    global las traduce a 409/422 correctamente sin necesitar este matiz.
    """
    try:
        async with get_auth_store(request) as store:
            user = await store.create_user(get_tenant_id(request), payload.username, payload.password, role_id=payload.role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _user_response(user)


@router.get("/api/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, request: Request) -> UserResponse:
    # UserNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_auth_store(request) as store:
        user = await store.get_user(get_tenant_id(request), user_id)
    return _user_response(user)


@router.patch("/api/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, payload: UpdateUserRequest, request: Request) -> UserResponse:
    """Actualiza el rol y/o restablece la contraseña de un usuario.

    Mismo matiz que `create_user`: `RoleNotFoundError` se captura aquí y se
    remapea a 422 porque `role_id` es una referencia en el payload, no el
    recurso de la URL. `UserNotFoundError`/`RoleInUseError`/`AuthError` se
    propagan sin capturar (404/409/422 vía el handler global).
    """
    try:
        async with get_auth_store(request) as store:
            user = await store.update_user(get_tenant_id(request), user_id, role_id=payload.role_id, password=payload.password)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _user_response(user)


@router.delete("/api/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request) -> None:
    # UserNotFoundError/RoleInUseError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 404/409.
    async with get_auth_store(request) as store:
        await store.delete_user(get_tenant_id(request), user_id)


__all__ = ["router"]
