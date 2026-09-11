"""
Pantalla cruzada "Tenants y usuarios" (rediseño Tenant/Role/User, decisión de
diseño 3): alta/baja de tenants y gestión de usuarios de CUALQUIER tenant, no
solo el propio -- exige `is_instance_admin`, a diferencia de `/admin/users`
(propio tenant, basta `is_admin`, ver `web/routes/admin.py`).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from doc_organize.core.exceptions import RoleNotFoundError
from doc_organize.core.models import User
from doc_organize.web.dependencies import get_auth_store, get_project_registry, require_instance_admin
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["tenants"], dependencies=[Depends(require_instance_admin)])


class TenantResponse(BaseModel):
    id: str
    name: str
    created_at: str
    user_count: int


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]


class CreateTenantRequest(BaseModel):
    name: str


class TenantUserResponse(BaseModel):
    id: str
    tenant_id: str
    username: str
    role_id: str
    must_change_password: bool
    is_blocked: bool
    is_instance_admin: bool
    created_at: str


class CreateTenantUserRequest(BaseModel):
    username: str
    password: str
    role_id: str
    must_change_password: bool = False


class UpdateTenantUserRequest(BaseModel):
    role_id: str | None = None
    password: str | None = None
    is_blocked: bool | None = None
    is_instance_admin: bool | None = None


def _tenant_user_response(user: User) -> TenantUserResponse:
    return TenantUserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        role_id=user.role_id,
        must_change_password=user.must_change_password,
        is_blocked=user.is_blocked,
        is_instance_admin=user.is_instance_admin,
        created_at=user.created_at,
    )


@router.get("/admin/tenants", response_class=HTMLResponse)
async def admin_tenants_page(request: Request) -> HTMLResponse:
    async with get_auth_store(request) as store:
        tenants = await store.list_tenants()
        users_by_tenant = {tenant.id: await store.list_users(tenant.id) for tenant in tenants}
        roles = await store.list_roles()
    roles_by_id = {role.id: role for role in roles}
    return _templates.TemplateResponse(
        request,
        "admin_tenants.html.j2",
        {"tenants": tenants, "users_by_tenant": users_by_tenant, "roles": roles, "roles_by_id": roles_by_id},
    )


@router.get("/api/tenants", response_model=TenantListResponse)
async def list_tenants(request: Request) -> TenantListResponse:
    async with get_auth_store(request) as store:
        tenants = await store.list_tenants()
        user_counts = {tenant.id: len(await store.list_users(tenant.id)) for tenant in tenants}
    return TenantListResponse(tenants=[TenantResponse(id=t.id, name=t.name, created_at=t.created_at, user_count=user_counts[t.id]) for t in tenants])


@router.post("/api/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(payload: CreateTenantRequest, request: Request) -> TenantResponse:
    # AuthError/TenantAlreadyExistsError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 422/409.
    async with get_auth_store(request) as store:
        tenant = await store.create_tenant(payload.name)
    return TenantResponse(id=tenant.id, name=tenant.name, created_at=tenant.created_at, user_count=0)


@router.delete("/api/tenants/{tenant_id}", status_code=204)
async def delete_tenant(tenant_id: str, request: Request) -> None:
    # TenantNotFoundError/TenantInUseError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 404/409.
    async with get_project_registry(request) as registry:
        has_projects = bool(await registry.list_projects(tenant_id=tenant_id))
    async with get_auth_store(request) as store:
        await store.delete_tenant(tenant_id, has_projects=has_projects)


@router.get("/api/tenants/{tenant_id}/users", response_model=list[TenantUserResponse])
async def list_tenant_users(tenant_id: str, request: Request) -> list[TenantUserResponse]:
    async with get_auth_store(request) as store:
        if not await store.tenant_exists(tenant_id):
            raise HTTPException(status_code=404, detail=f"No existe ningún tenant con id '{tenant_id}'.")
        users = await store.list_users(tenant_id)
    return [_tenant_user_response(user) for user in users]


@router.post("/api/tenants/{tenant_id}/users", response_model=TenantUserResponse, status_code=201)
async def create_tenant_user(tenant_id: str, payload: CreateTenantUserRequest, request: Request) -> TenantUserResponse:
    """Crea el primer (o enésimo) usuario de `tenant_id` -- necesario porque
    `AuthStore.create_tenant()` ya no aprovisiona ningún usuario automáticamente
    (rediseño Tenant/Role/User): esta es la vía normal para dar de alta usuarios
    en un tenant recién creado, salvo que se prefiera `user create` por CLI.

    Mismo matiz que `web/routes/admin.py::create_user`: `RoleNotFoundError` se
    remapea a 422 (referencia en el payload, no el recurso de la URL).
    """
    try:
        async with get_auth_store(request) as store:
            user = await store.create_user(
                tenant_id,
                payload.username,
                payload.password,
                role_id=payload.role_id,
                must_change_password=payload.must_change_password,
            )
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _tenant_user_response(user)


@router.patch("/api/tenants/{tenant_id}/users/{user_id}", response_model=TenantUserResponse)
async def update_tenant_user(tenant_id: str, user_id: str, payload: UpdateTenantUserRequest, request: Request) -> TenantUserResponse:
    """Actualiza rol, contraseña, bloqueo y/o `is_instance_admin` de un usuario de
    CUALQUIER tenant -- variante de `web/routes/admin.py::update_user` sin la
    restricción al tenant de la sesión, y la única ruta que puede tocar
    `is_instance_admin` (decisión de diseño 3: solo otro `is_instance_admin`
    puede concederlo/retirarlo).
    """
    try:
        async with get_auth_store(request) as store:
            user = await store.update_user(tenant_id, user_id, role_id=payload.role_id, password=payload.password)
            if payload.is_blocked is not None:
                user = await store.set_user_blocked(tenant_id, user_id, payload.is_blocked)
            if payload.is_instance_admin is not None:
                user = await store.set_instance_admin(tenant_id, user_id, payload.is_instance_admin)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _tenant_user_response(user)


@router.delete("/api/tenants/{tenant_id}/users/{user_id}", status_code=204)
async def delete_tenant_user(tenant_id: str, user_id: str, request: Request) -> None:
    # UserNotFoundError/RoleInUseError se propagan sin capturar: el handler
    # global de web/app.py (_EXCEPTION_STATUS_CODES) las traduce a 404/409.
    async with get_auth_store(request) as store:
        await store.delete_user(tenant_id, user_id)


__all__ = ["router"]
