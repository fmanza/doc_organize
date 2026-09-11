"""
Gestión de roles y usuarios (revisión 9; rediseño Tenant/Role/User): CRUD
admin-only sobre `AuthStore`, con `Role` ya global (sin tenant) y `User` con
`is_blocked`/`is_instance_admin`.

Todas las rutas de este router exigen `require_admin_or_instance_admin`
(declarado a nivel de `APIRouter`, no por endpoint — imposible olvidarlo en una
ruta nueva): basta `is_admin` del propio tenant, o `is_instance_admin` de
cualquiera. En loopback/sin auth no hay sesión que resolver, así que no se
aplica ninguna restricción ahí (mismo criterio que el resto de la app).

`Role` ya no está ligado a un tenant, así que `/api/roles*` opera sobre el
catálogo global completo (mismo catálogo que ve la pantalla cruzada de
`web/routes/tenants.py`) — lo único filtrado por el tenant de la sesión es la
lista de "usuarios asignados" que muestra `/admin/roles` (AUDIT_PLAN, condición
de no-enumeración cross-tenant: un admin de un solo tenant no debe ver
usernames de otro tenant a través de un rol compartido).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from doc_organize.core.constants import ROLE_NAME_MAX_LENGTH, USERNAME_MAX_LENGTH
from doc_organize.core.exceptions import RoleNotFoundError
from doc_organize.core.models import Role, User
from doc_organize.web.dependencies import get_auth_store, get_project_registry, get_tenant_id, require_admin_or_instance_admin
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin_or_instance_admin)])


class RoleResponse(BaseModel):
    id: str
    name: str
    is_admin: bool
    project_names: list[str]
    created_at: str


class RoleListResponse(BaseModel):
    roles: list[RoleResponse]


class CreateRoleRequest(BaseModel):
    name: str
    is_admin: bool = False
    project_names: list[str] = []


class UpdateRoleRequest(BaseModel):
    name: str | None = None
    is_admin: bool | None = None
    project_names: list[str] | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    role_id: str
    must_change_password: bool
    is_blocked: bool
    is_instance_admin: bool
    created_at: str


class UserListResponse(BaseModel):
    users: list[UserResponse]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role_id: str
    must_change_password: bool = False


class UpdateUserRequest(BaseModel):
    role_id: str | None = None
    password: str | None = None
    is_blocked: bool | None = None


def _role_response(role: Role) -> RoleResponse:
    return RoleResponse(id=role.id, name=role.name, is_admin=role.is_admin, project_names=role.project_names, created_at=role.created_at)


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role_id=user.role_id,
        must_change_password=user.must_change_password,
        is_blocked=user.is_blocked,
        is_instance_admin=user.is_instance_admin,
        created_at=user.created_at,
    )


@router.get("/admin/roles", response_class=HTMLResponse)
async def admin_roles_page(request: Request) -> HTMLResponse:
    tenant_id = get_tenant_id(request)
    async with get_auth_store(request) as store:
        roles = await store.list_roles()
        # "Usuarios asignados" por rol, filtrado al tenant de la sesión: un rol es
        # global y puede estar en uso en varios tenants a la vez (ver docstring del
        # módulo) -- mostrar aquí usernames de OTRO tenant sería una fuga nueva que
        # este propio rediseño introduciría si no se filtrara.
        assigned_usernames_by_role = {
            role.id: sorted(user.username for user in await store.users_for_role(role.id) if user.tenant_id == tenant_id) for role in roles
        }
    async with get_project_registry(request) as registry:
        projects = await registry.list_projects(tenant_id=tenant_id)
    return _templates.TemplateResponse(
        request,
        "admin_roles.html.j2",
        {
            "roles": roles,
            "projects": projects,
            "role_name_max_length": ROLE_NAME_MAX_LENGTH,
            "assigned_usernames_by_role": assigned_usernames_by_role,
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request) -> HTMLResponse:
    tenant_id = get_tenant_id(request)
    async with get_auth_store(request) as store:
        users = await store.list_users(tenant_id)
        roles = await store.list_roles()
    roles_by_id = {role.id: role for role in roles}
    return _templates.TemplateResponse(
        request,
        "admin_users.html.j2",
        {"users": users, "roles": roles, "roles_by_id": roles_by_id, "username_max_length": USERNAME_MAX_LENGTH},
    )


@router.get("/api/roles", response_model=RoleListResponse)
async def list_roles(request: Request) -> RoleListResponse:
    async with get_auth_store(request) as store:
        roles = await store.list_roles()
    return RoleListResponse(roles=[_role_response(role) for role in roles])


@router.post("/api/roles", response_model=RoleResponse, status_code=201)
async def create_role(payload: CreateRoleRequest, request: Request) -> RoleResponse:
    # RoleAlreadyExistsError/AuthError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 409/422.
    async with get_auth_store(request) as store:
        role = await store.create_role(payload.name, is_admin=payload.is_admin, project_names=payload.project_names)
    return _role_response(role)


@router.get("/api/roles/{role_id}", response_model=RoleResponse)
async def get_role(role_id: str, request: Request) -> RoleResponse:
    # RoleNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_auth_store(request) as store:
        role = await store.get_role(role_id)
    return _role_response(role)


@router.patch("/api/roles/{role_id}", response_model=RoleResponse)
async def update_role(role_id: str, payload: UpdateRoleRequest, request: Request) -> RoleResponse:
    # RoleNotFoundError/RoleAlreadyExistsError/AuthError se propagan sin
    # capturar: el handler global de web/app.py (_EXCEPTION_STATUS_CODES)
    # las traduce a 404/409/422 respectivamente.
    async with get_auth_store(request) as store:
        role = await store.update_role(role_id, name=payload.name, is_admin=payload.is_admin, project_names=payload.project_names)
    return _role_response(role)


@router.delete("/api/roles/{role_id}", status_code=204)
async def delete_role(role_id: str, request: Request) -> None:
    # RoleNotFoundError/RoleInUseError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 404/409.
    async with get_auth_store(request) as store:
        await store.delete_role(role_id)


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
            user = await store.create_user(
                get_tenant_id(request),
                payload.username,
                payload.password,
                role_id=payload.role_id,
                must_change_password=payload.must_change_password,
            )
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
    """Actualiza rol, contraseña y/o bloqueo de un usuario.

    Mismo matiz que `create_user`: `RoleNotFoundError` se captura aquí y se
    remapea a 422 porque `role_id` es una referencia en el payload, no el
    recurso de la URL. `UserNotFoundError`/`RoleInUseError`/`AuthError` se
    propagan sin capturar (404/409/422 vía el handler global).

    `is_blocked`, si se pasa, se aplica en una segunda llamada a `AuthStore`
    (`set_user_blocked`, que invalida sesiones activas al bloquear) — no forma
    parte de `update_user` porque es una preocupación distinta (revocación
    inmediata de acceso, no reasignación de rol/contraseña).
    """
    tenant_id = get_tenant_id(request)
    try:
        async with get_auth_store(request) as store:
            user = await store.update_user(tenant_id, user_id, role_id=payload.role_id, password=payload.password)
            if payload.is_blocked is not None:
                user = await store.set_user_blocked(tenant_id, user_id, payload.is_blocked)
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
