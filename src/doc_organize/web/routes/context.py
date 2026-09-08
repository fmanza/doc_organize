"""
Organización documental por dominios y contextos: construir/ver el contexto de un proyecto.
"""

import asyncio

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from doc_organize.ai import DomainClassificationClient, litellm_classification_config_from_env
from doc_organize.cache import CacheManager
from doc_organize.context import ContextBuilder, ContextRegistry, MkDocsGenerator, Reorganizer
from doc_organize.converter import DocumentConverter
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.exceptions import ContextNotFoundError
from doc_organize.core.models import Context, ConversionResult, ConversionStatus, Project
from doc_organize.web.dependencies import (
    get_project_registry,
    get_scanned_folders_store,
    get_tenant_id,
    project_operation_key,
    require_project_access,
)
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["context"])

_context_registry = ContextRegistry()
_context_builder = ContextBuilder(_context_registry)
_reorganizer = Reorganizer()
_mkdocs_generator = MkDocsGenerator()


class BuildContextRequest(BaseModel):
    candidate_domains: list[str] | None = None
    threshold: float = 0.5
    ai_classification_enabled: bool = False


class DomainSummary(BaseModel):
    slug: str
    name: str
    status: str
    document_count: int


class ContextResponse(BaseModel):
    output_folder_name: str
    domains: list[DomainSummary]
    unclassified_count: int
    reorganized: bool
    mkdocs_generated: bool
    ai_classification_enabled: bool


def _acquire_operation_lock(request: Request, tenant_id: str, project_name: str) -> tuple[str, str]:
    """Reserva `(tenant_id, project_name)` para esta petición, o levanta 409 si ya
    hay un escaneo, deduplicación u otra operación en curso para este proyecto.

    Mismo criterio que `projects.py::_acquire_operation_lock` (duplicado aquí, no
    importado, para no tocar ese módulo — política "prohibido refactorizar" de
    `/new-feature`): ambos leen/escriben el mismo `app.state.active_project_operations`
    vía la clave compartida `project_operation_key()`, así que se bloquean
    mutuamente sobre el mismo proyecto igual que ya hacen escaneo/dedup/mover/borrar
    (AUDIT_CODE, sesión 2026-09-08 — construir el contexto mientras un escaneo
    reescribe `Conversión/` podía dejar `Reorganizer` copiando ficheros a medio
    escribir, o dos reconstrucciones concurrentes pisándose entre sí).
    """
    key = project_operation_key(tenant_id, project_name)
    active = request.app.state.active_project_operations
    if key in active:
        raise HTTPException(status_code=409, detail="Ya hay un escaneo, deduplicación u otra operación en curso para este proyecto.")
    active.add(key)
    return key


def _release_operation_lock(request: Request, key: tuple[str, str]) -> None:
    request.app.state.active_project_operations.discard(key)


@asynccontextmanager
async def _optional_ai_client(enabled: bool) -> AsyncIterator[DomainClassificationClient | None]:
    """`None` si la Sub-fase B no está activa; si lo está, construye el cliente
    desde el entorno (`litellm_classification_config_from_env()`) y lo cierra al
    salir. `DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY` sin
    definir se traduce en 400, no en un 500 críptico — el usuario activó el
    toggle de IA, pero el proxy de clasificación no está configurado todavía
    (ver `docs/guides/litellm_proxy_setup.md`)."""
    if not enabled:
        yield None
        return
    try:
        config = litellm_classification_config_from_env()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with DomainClassificationClient(config) as client:
        yield client


async def _get_project(request: Request, name: str) -> Project:
    # ProjectNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    async with get_project_registry(request) as registry:
        return await registry.get_project(name, tenant_id=get_tenant_id(request))


async def _gather_converted_documents(project: Project) -> list[ConversionResult]:
    """Reconstruye un `ConversionResult` por cada fichero ya convertido con éxito
    en `cache.db`, recalculando `markdown_path`/`json_path` con
    `DocumentConverter.resolve_output_paths()` — determinista a partir de la ruta
    origen + las carpetas de escaneo guardadas, no hace falta persistir esas
    rutas de salida por separado (mismo criterio que `ScanCommand._delete_orphaned_outputs`).

    Omite las entradas cuyo original ya no existe en `entry.file_path`: `dedup/`
    no actualiza `cache.db` al mover un duplicado a `duplicados/`, así que una
    entrada `SUCCESS` puede seguir apuntando a un fichero que ya no está ahí
    hasta el siguiente escaneo. Sin este filtro, `Reorganizer` fallaba con
    `IncompleteConversionArtifactsError` para documentos que en realidad ya
    están correctamente gestionados (como duplicado), no rotos (AUDIT_CODE,
    sesión 2026-09-09).
    """
    cache_db = Path(project.root_path) / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        entries = await cache.load_cache()

    scan_roots = [folder.path for folder in await get_scanned_folders_store().list_folders(project)]
    output_dir = Path(project.root_path) / "Conversión"

    documents = []
    for entry in entries.values():
        if entry.conversion_status != ConversionStatus.SUCCESS:
            continue
        if not await asyncio.to_thread(Path(entry.file_path).is_file):
            continue
        markdown_path, json_path = DocumentConverter.resolve_output_paths(entry.file_path, output_dir, scan_roots)
        documents.append(ConversionResult(source_path=entry.file_path, markdown_path=str(markdown_path), json_path=str(json_path), success=True))
    return documents


def _to_response(context: Context) -> ContextResponse:
    return ContextResponse(
        output_folder_name=context.output_folder_name,
        domains=[
            DomainSummary(slug=domain.slug, name=domain.name, status=domain.status.value, document_count=len(domain.documents))
            for domain in context.domains
        ],
        unclassified_count=len(context.unclassified_documents),
        reorganized=context.reorganized,
        mkdocs_generated=context.mkdocs_generated,
        ai_classification_enabled=context.ai_classification_enabled,
    )


@router.post("/api/projects/{name}/context", response_model=ContextResponse, dependencies=[Depends(require_project_access)])
async def build_context(name: str, request: Request, payload: BuildContextRequest | None = None) -> ContextResponse:
    """Construye (o reconstruye) el contexto de `name`: clasifica los documentos ya
    convertidos (Sub-fase A), los copia a `<output_folder_name>/` y genera `mkdocs.yml`.

    Si `reorganize()`/`generate()` fallan a mitad, `context.json` se persiste de
    todas formas (en el `finally`) con `reorganized`/`mkdocs_generated` reflejando
    lo que de verdad se completó — nunca queda un contexto que diga "todo bien"
    cuando la copia física o el sitio MkDocs se quedaron a medias (AUDIT_CODE,
    sesión 2026-09-08).
    """
    payload = payload or BuildContextRequest()
    tenant_id = get_tenant_id(request)
    key = _acquire_operation_lock(request, tenant_id, name)
    try:
        project = await _get_project(request, name)
        documents = await _gather_converted_documents(project)

        async with _optional_ai_client(payload.ai_classification_enabled) as ai_client:
            context = await _context_builder.build(
                project,
                documents,
                candidate_domains=payload.candidate_domains,
                threshold=payload.threshold,
                ai_classification_enabled=payload.ai_classification_enabled,
                ai_classification_client=ai_client,
            )
        try:
            await _reorganizer.reorganize(project, context)
            context.reorganized = True
            await _mkdocs_generator.generate(project, context)
            context.mkdocs_generated = True
        finally:
            await _context_registry.save_context(project, context)
        return _to_response(context)
    finally:
        _release_operation_lock(request, key)


@router.get("/api/projects/{name}/context", response_model=ContextResponse, dependencies=[Depends(require_project_access)])
async def get_context_api(name: str, request: Request) -> ContextResponse:
    # ContextNotFoundError se propaga sin capturar: el handler global de
    # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
    project = await _get_project(request, name)
    context = await _context_registry.load_context(project)
    return _to_response(context)


@router.get("/projects/{name}/context", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def context_page(name: str, request: Request) -> HTMLResponse:
    project = await _get_project(request, name)
    context: Context | None
    try:
        context = await _context_registry.load_context(project)
    except ContextNotFoundError:
        context = None
    return _templates.TemplateResponse(request, "context.html.j2", {"project": project, "context": context})


__all__ = ["router"]
