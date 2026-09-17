"""
Biblioteca de plantillas de manifiesto de taxonomía (config de instancia, admin-only).

Separado de `context.py` (construcción/consulta del contexto de un PROYECTO concreto):
son dos dominios de rutas sin relación entre sí -- este módulo no depende de ningún
proyecto ni tenant, solo de `TaxonomyTemplateRegistry` (biblioteca compartida de la
instancia). Split motivado por deuda técnica (`/tech-debt`, sesión 2026-09-17):
`context.py` mezclaba ambos dominios en un único fichero de 1000+ líneas.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from doc_organize.core.exceptions import TaxonomyTemplateError
from doc_organize.core.models import TaxonomyCatalogEntry, TaxonomyManifest, TaxonomyTemplateSummary
from doc_organize.web.dependencies import get_taxonomy_template_registry, require_instance_admin
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["taxonomy-templates"])


class ConfirmedActionRequest(BaseModel):
    # Duplicado intencional de `projects.py::ConfirmedActionRequest` (mismo criterio que
    # `web/routes/context.py::ConfirmedActionRequest`) -- política "prohibido refactorizar"
    # de `/new-feature`.
    confirm: bool = False


class TaxonomyTemplateListResponse(BaseModel):
    templates: list[TaxonomyTemplateSummary]


class TaxonomyTemplateSaveRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    domains: list[TaxonomyCatalogEntry] = Field(min_length=1)
    material_types: list[TaxonomyCatalogEntry] = Field(min_length=1)


class TaxonomyTemplateResponse(BaseModel):
    name: str
    manifest: TaxonomyManifest


@router.get("/api/taxonomy-templates", response_model=TaxonomyTemplateListResponse)
async def list_taxonomy_templates(request: Request) -> TaxonomyTemplateListResponse:
    """Lista las plantillas de manifiesto de taxonomía disponibles (biblioteca compartida
    de `TaxonomyTemplateRegistry`, no ligada a ningún proyecto ni tenant concreto), para
    poblar el selector de `payload.taxonomy_template_name` (`POST .../context`)."""
    template_registry = get_taxonomy_template_registry(request)
    return TaxonomyTemplateListResponse(templates=await template_registry.list_templates())


@router.get("/api/taxonomy-templates/{template_name}", response_model=TaxonomyTemplateResponse)
async def get_taxonomy_template(template_name: str, request: Request) -> TaxonomyTemplateResponse:
    """Contenido completo (catálogos + título/descripción) de la plantilla `template_name`.

    A diferencia de `list_taxonomy_templates` (solo `TaxonomyTemplateSummary`, sin catálogos),
    usado por `/admin/plantillas-taxonomia` para prefijar el formulario de edición.

    Raises:
        HTTPException: 404 si no existe ninguna plantilla con ese nombre.
    """
    template_registry = get_taxonomy_template_registry(request)
    try:
        manifest = await template_registry.load_template(template_name)
    except TaxonomyTemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaxonomyTemplateResponse(name=template_name, manifest=manifest)


@router.put(
    "/api/taxonomy-templates/{template_name}",
    response_model=TaxonomyTemplateResponse,
    dependencies=[Depends(require_instance_admin)],
)
async def save_taxonomy_template(template_name: str, payload: TaxonomyTemplateSaveRequest, request: Request) -> TaxonomyTemplateResponse:
    """Crea (o sobrescribe) la plantilla `template_name` en la biblioteca de usuario -- admin-only,
    igual criterio que `/admin/roles`/`/admin/users` (config de instancia, no de un proyecto).

    `PUT` en vez de `POST`+`PUT` separados: la semántica de "crear o reemplazar por identificador
    en la URL" es la misma operación de fichero (`TaxonomyTemplateRegistry.save_template` siempre
    sobrescribe), así que un único endpoint idempotente cubre ambos casos sin distinguir 201 de 200
    -- no hay ninguna diferencia de comportamiento entre "crear" y "editar" aquí.

    Raises:
        HTTPException: 400 si `template_name` no es un slug válido (solo minúsculas, dígitos y
            guiones).
    """
    template_registry = get_taxonomy_template_registry(request)
    manifest = TaxonomyManifest(title=payload.title, description=payload.description, domains=payload.domains, material_types=payload.material_types)
    try:
        await template_registry.save_template(template_name, manifest)
    except TaxonomyTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaxonomyTemplateResponse(name=template_name, manifest=manifest)


@router.delete(
    "/api/taxonomy-templates/{template_name}",
    status_code=204,
    dependencies=[Depends(require_instance_admin)],
)
async def delete_taxonomy_template(template_name: str, payload: ConfirmedActionRequest, request: Request) -> None:
    """Elimina la plantilla de usuario `template_name` -- admin-only.

    Nunca borra una plantilla empaquetada (`TaxonomyTemplateRegistry.delete_template` solo toca
    `templates_dir`, ver su docstring) -- si `template_name` solo existe como empaquetada, se
    levanta 404 igual que "no existe", nunca se confunde con éxito.

    Operación irreversible -- requiere confirmación explícita (`confirm: true`), mismo criterio
    que `delete_context_endpoint` (`web/routes/context.py`).

    Raises:
        HTTPException: 400 si `confirm` no es `true`; 404 si no existe ninguna plantilla de
            usuario con ese nombre.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Se requiere confirmación explícita para eliminar la plantilla.")
    template_registry = get_taxonomy_template_registry(request)
    try:
        await template_registry.delete_template(template_name)
    except TaxonomyTemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/admin/plantillas-taxonomia", response_class=HTMLResponse, dependencies=[Depends(require_instance_admin)])
async def taxonomy_templates_admin_page(request: Request) -> HTMLResponse:
    """Biblioteca de plantillas de taxonomía (crear/editar/borrar) -- config de instancia
    (no de un proyecto concreto, ni de un tenant concreto), por eso exige
    `is_instance_admin` y no solo `is_admin` de tenant (rediseño Tenant/Role/User)."""
    template_registry = get_taxonomy_template_registry(request)
    templates_list = await template_registry.list_templates()
    return _templates.TemplateResponse(
        request,
        "taxonomy_templates_admin.html.j2",
        {"templates": [template.model_dump() for template in templates_list]},
    )


__all__ = ["router"]
