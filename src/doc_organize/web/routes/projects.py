"""
Rutas de gestión de proyectos (REQ-008 vía HTTP, contrato REQ-007 §8.2).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from doc_organize.core.exceptions import (
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectNameError,
    ProjectNotFoundError,
)
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import get_project_registry, get_tenant_id

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


@router.post("", response_model=ProjectResponse, status_code=201)
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
    async with get_project_registry(request) as registry:
        projects = await registry.list_projects(tenant_id=get_tenant_id(request))
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


@router.get("/{name}", response_model=ProjectResponse)
async def get_project(name: str, request: Request) -> ProjectResponse:
    try:
        async with get_project_registry(request) as registry:
            project = await registry.get_project(name, tenant_id=get_tenant_id(request))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectResponse(name=project.name, root_path=project.root_path, created_at=project.created_at)


__all__ = ["router"]
