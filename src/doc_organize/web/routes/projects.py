"""
Rutas de gestión de proyectos (REQ-008 vía HTTP, contrato REQ-007 §8.2).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from doc_organize.core.exceptions import (
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectNameError,
    ProjectNotFoundError,
)
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import get_auth_store, get_project_registry, get_tenant_id, require_admin, require_project_access

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    base_location: str


class ProjectResponse(BaseModel):
    name: str
    root_path: str
    created_at: str


class ProjectListItem(ProjectResponse):
    missing: bool


class ProjectListResponse(BaseModel):
    projects: list[ProjectListItem]


@router.post("", response_model=ProjectResponse, status_code=201, dependencies=[Depends(require_admin)])
async def create_project(payload: CreateProjectRequest, request: Request) -> ProjectResponse:
    tenant_id = get_tenant_id(request)
    try:
        async with get_project_registry(request) as registry:
            project = await registry.create_project(payload.name, Path(payload.base_location), tenant_id=tenant_id)
    except ProjectAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectResponse(name=project.name, root_path=project.root_path, created_at=project.created_at)


@router.get("", response_model=ProjectListResponse)
async def list_projects(request: Request) -> ProjectListResponse:
    """Lista los proyectos del tenant, filtrados por acceso (revisión 9).

    Un rol `is_admin` ve todos; un rol restringido solo los de su `project_names`.
    Sin sesión resuelta (loopback/sin auth), no se aplica ningún filtro — mismo
    criterio que `get_tenant_id`.
    """
    async with get_project_registry(request) as registry:
        projects = await registry.list_projects(tenant_id=get_tenant_id(request))

    if getattr(request.state, "is_admin", None) is False:
        async with get_auth_store(request) as store:
            role = await store.get_role(get_tenant_id(request), request.state.role_id)
        allowed_names = {allowed.lower() for allowed in role.project_names}
        projects = [project for project in projects if project.name.lower() in allowed_names]

    items = [
        ProjectListItem(
            name=project.name,
            root_path=project.root_path,
            created_at=project.created_at,
            missing=not Path(project.root_path).exists(),
        )
        for project in projects
    ]
    return ProjectListResponse(projects=items)


@router.get("/{name}", response_model=ProjectResponse, dependencies=[Depends(require_project_access)])
async def get_project(name: str, request: Request) -> ProjectResponse:
    try:
        async with get_project_registry(request) as registry:
            project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectResponse(name=project.name, root_path=project.root_path, created_at=project.created_at)


__all__ = ["router"]
