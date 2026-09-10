"""
Organización documental por dominios y contextos: construir/ver el contexto de un proyecto.
"""

import asyncio
import json
import re

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, ValidationError

from doc_organize.ai import DomainClassificationClient, litellm_classification_config_from_env
from doc_organize.cache import CacheManager
from doc_organize.context import ContextBuilder, ContextRegistry, MkDocsGenerator, Reorganizer
from doc_organize.converter import DocumentConverter
from doc_organize.core.constants import (
    CONVERSION_FOLDER_NAME,
    DEFAULT_CACHE_DB_NAME,
    DUPLICATES_FOLDER_NAME,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_HISTORY_FOLDER_NAME,
)
from doc_organize.core.exceptions import ContextNotFoundError, ProjectNotFoundError
from doc_organize.core.models import (
    Context,
    ContextBuildEvent,
    ContextBuildEventType,
    ContextDeleteEvent,
    ContextDeleteEventType,
    ConversionResult,
    ConversionStatus,
    Project,
)
from doc_organize.utils.logging import get_logger
from doc_organize.web.dependencies import (
    acquire_project_operation_lock,
    authorize_project_websocket,
    get_project_registry,
    get_scanned_folders_store,
    get_tenant_id,
    project_operation_key,
    release_project_operation_lock,
    require_project_access,
)
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)
logger = get_logger(__name__)

router = APIRouter(tags=["context"])

_context_registry = ContextRegistry()
_context_builder = ContextBuilder(_context_registry)
_reorganizer = Reorganizer()
_mkdocs_generator = MkDocsGenerator()

_DEFAULT_OUTPUT_FOLDER_NAME = "organizado"
_OUTPUT_FOLDER_NAME_PATTERN = re.compile(r"^[\w.\- ]+$")
# Carpetas de `project.root_path` ya reservadas por otros subsistemas ("domains" en
# ContextRegistry, "site" en MkDocsGenerator — sin constante importable propia, son
# privadas a su módulo). Si `output_folder_name` coincidiera con una de estas,
# `Reorganizer` escribiría dentro de la carpeta de otro subsistema y
# `delete_context_endpoint` podría borrarla entera vía `Reorganizer.delete_output()`
# (AUDIT_CODE, sesión 2026-09-10 — ver p. ej. la colisión con `CONVERSION_FOLDER_NAME`:
# borraría todo lo convertido del proyecto).
_RESERVED_OUTPUT_FOLDER_NAMES = frozenset(
    name.casefold() for name in (DUPLICATES_FOLDER_NAME, SCAN_ERRORS_FOLDER_NAME, SCAN_HISTORY_FOLDER_NAME, CONVERSION_FOLDER_NAME, "domains", "site")
)

# Duplicado de `MkDocsGenerator._SITE_DIR_NAME` (privada a su módulo) — política
# "prohibido refactorizar" de `/new-feature`, mismo criterio que `ConfirmedActionRequest`.
_SITE_DIR_NAME = "site"
_SITE_INDEX_NAME = "index.html"


class BuildContextRequest(BaseModel):
    candidate_domains: list[str] | None = None
    threshold: float = 0.5
    ai_classification_enabled: bool = False
    output_folder_name: str | None = None
    """Nombre de la carpeta de copia organizada. Solo tiene efecto en la primera
    construcción del contexto de un proyecto (cuando no hay `context.json` todavía)
    — en reconstrucciones posteriores se ignora y se reutiliza el valor ya
    persistido, ver `_resolve_output_folder_name()`."""


class ConfirmedActionRequest(BaseModel):
    # Duplicado intencional de `projects.py::ConfirmedActionRequest` — mismo criterio
    # que `_acquire_operation_lock` (política "prohibido refactorizar" de `/new-feature`).
    confirm: bool = False


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
    mkdocs_site_built: bool
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


async def _load_existing_context_or_none(project: Project) -> Context | None:
    try:
        return await _context_registry.load_context(project)
    except ContextNotFoundError:
        return None


def _resolve_output_folder_name(existing_context: Context | None, requested: str | None) -> str:
    """`output_folder_name` solo es elegible en la primera construcción de un
    proyecto (`existing_context is None`): una vez hay un contexto, el nombre
    queda fijo y cualquier valor recibido en reconstrucciones se ignora — para
    cambiarlo el usuario debe eliminar el contexto primero (`delete_context_endpoint`),
    que también borra la copia física, así nunca queda una carpeta huérfana de un
    nombre anterior conviviendo con una nueva.

    Raises:
        HTTPException: 400 si `requested` no es un nombre de carpeta simple (sin
            separadores de ruta ni `..`), o si coincide (sin distinguir mayúsculas)
            con una carpeta ya reservada por otro subsistema del proyecto
            (`_RESERVED_OUTPUT_FOLDER_NAMES`) — evita tanto escribir fuera de
            `root_path` como pisar/heredar el borrado de una carpeta ajena.
    """
    if existing_context is not None:
        return existing_context.output_folder_name
    if requested is None or not requested.strip():
        return _DEFAULT_OUTPUT_FOLDER_NAME
    candidate = requested.strip()
    if candidate in {".", ".."} or not _OUTPUT_FOLDER_NAME_PATTERN.fullmatch(candidate):
        raise HTTPException(status_code=400, detail=f"Nombre de carpeta de salida inválido: '{requested}'.")
    if candidate.casefold() in _RESERVED_OUTPUT_FOLDER_NAMES:
        raise HTTPException(status_code=400, detail=f"'{requested}' es un nombre de carpeta reservado por el proyecto — elige otro.")
    return candidate


async def _gather_converted_documents(project: Project) -> list[ConversionResult]:
    """Reconstruye un `ConversionResult` por cada fichero ya convertido con éxito
    en `cache.db`, recalculando `markdown_path`/`json_path`/`images_dir` con
    `DocumentConverter.resolve_output_paths()`/`resolve_images_dir()` — determinista
    a partir de la ruta origen + las carpetas de escaneo guardadas, no hace falta
    persistir esas rutas de salida por separado (mismo criterio que
    `ScanCommand._delete_orphaned_outputs`). `images_dir` no se persiste en
    `cache.db` ni en `document.json`, así que hay que recalcularlo igual que
    `markdown_path`/`json_path` — de lo contrario `Reorganizer` nunca recibe la
    carpeta de imágenes y MkDocs las sirve rotas (AUDIT_CODE, sesión 2026-09-10).

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
    output_dir = Path(project.root_path) / CONVERSION_FOLDER_NAME

    documents = []
    for entry in entries.values():
        if entry.conversion_status != ConversionStatus.SUCCESS:
            continue
        if not await asyncio.to_thread(Path(entry.file_path).is_file):
            continue
        markdown_path, json_path = DocumentConverter.resolve_output_paths(entry.file_path, output_dir, scan_roots)
        images_dir = DocumentConverter.resolve_images_dir(markdown_path)
        images_dir_str = str(images_dir) if await asyncio.to_thread(images_dir.is_dir) else None
        documents.append(
            ConversionResult(
                source_path=entry.file_path, markdown_path=str(markdown_path), json_path=str(json_path), images_dir=images_dir_str, success=True
            )
        )
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
        mkdocs_site_built=context.mkdocs_site_built,
        ai_classification_enabled=context.ai_classification_enabled,
    )


@router.post("/api/projects/{name}/context", response_model=ContextResponse, dependencies=[Depends(require_project_access)])
async def build_context(name: str, request: Request, payload: BuildContextRequest | None = None) -> ContextResponse:
    """Construye (o reconstruye) el contexto de `name`: clasifica los documentos ya
    convertidos (Sub-fase A), los copia a `<output_folder_name>/` y genera `mkdocs.yml`
    (+ `mkdocs build` si `mkdocs` está instalado, ver `MkDocsGenerator`).

    `payload.output_folder_name` solo tiene efecto en la primera construcción del
    proyecto — en reconstrucciones se ignora y se reutiliza el nombre ya persistido
    (ver `_resolve_output_folder_name()`); para cambiarlo hay que eliminar el
    contexto primero (`DELETE .../context`).

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
        existing_context = await _load_existing_context_or_none(project)
        output_folder_name = _resolve_output_folder_name(existing_context, payload.output_folder_name)

        async with _optional_ai_client(payload.ai_classification_enabled) as ai_client:
            context = await _context_builder.build(
                project,
                documents,
                candidate_domains=payload.candidate_domains,
                threshold=payload.threshold,
                ai_classification_enabled=payload.ai_classification_enabled,
                ai_classification_client=ai_client,
                output_folder_name=output_folder_name,
            )
        try:
            await _reorganizer.reorganize(project, context)
            context.reorganized = True
            _, site_built = await _mkdocs_generator.generate(project, context)
            context.mkdocs_generated = True
            context.mkdocs_site_built = site_built
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


@router.delete("/api/projects/{name}/context", status_code=204, dependencies=[Depends(require_project_access)])
async def delete_context_endpoint(name: str, payload: ConfirmedActionRequest, request: Request) -> None:
    """Elimina el contexto de `name` por completo: `context.json` + `domains/` +
    la copia física (`<output_folder_name>/`) + `mkdocs.yml`/`site/` — vuelve al
    estado anterior a la primera construcción, para poder elegir otro
    `output_folder_name` en la siguiente (`output_folder_name` queda fijo mientras
    exista un contexto, ver `_resolve_output_folder_name()`).

    Operación irreversible (borra documentos copiados de verdad) — requiere
    confirmación explícita en el payload (`confirm: true`), mismo criterio que
    `projects.py::delete_project`.

    Raises:
        HTTPException: 400 si `confirm` no es `true`; 404 si el proyecto no tiene
            contexto construido; 409 si hay otra operación en curso.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Se requiere confirmación explícita para eliminar el contexto.")

    tenant_id = get_tenant_id(request)
    key = _acquire_operation_lock(request, tenant_id, name)
    try:
        project = await _get_project(request, name)
        # ContextNotFoundError se propaga sin capturar: el handler global de
        # web/app.py (_EXCEPTION_STATUS_CODES) la traduce a 404.
        context = await _context_registry.load_context(project)

        # Limpieza física antes de borrar context.json: si algo falla a mitad,
        # context.json sigue existiendo como fuente de verdad de qué queda por
        # limpiar en un reintento (mismo criterio defensivo que el `finally` de
        # `build_context`).
        await _reorganizer.delete_output(project, context)
        await _mkdocs_generator.delete_site(project)
        await _context_registry.delete_context(project)
    finally:
        _release_operation_lock(request, key)


@router.websocket("/api/projects/{name}/context/build")
async def context_build_websocket(name: str, websocket: WebSocket) -> None:
    """Construye (o reconstruye) el contexto de `name`, retransmitiendo progreso
    (semáforo) como `ContextBuildEvent` JSON — equivalente en efectos a
    `build_context()` (REST), del que reutiliza toda la lógica de validación y
    orquestación, pero con eventos en tiempo real para la Sub-fase B (IA) y para
    `Reorganizer.reorganize()` (mismo patrón que `scan_websocket`/`ScanEvent`).
    """
    await websocket.accept()

    auth_result = await authorize_project_websocket(websocket, name)
    if auth_result is None:
        return
    tenant_id, _allowed_scan_roots = auth_result  # construir/eliminar contexto no acepta rutas de filesystem del cliente

    operation_key = await acquire_project_operation_lock(websocket, tenant_id, name)
    if operation_key is None:
        return
    try:
        async with get_project_registry(websocket) as registry:
            try:
                project = await registry.get_project(name, tenant_id=tenant_id)
            except ProjectNotFoundError:
                await websocket.close(code=1008, reason="Project not found")
                return

        try:
            request_payload = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await websocket.close(code=1008, reason="El payload debe ser JSON válido")
            return
        if not isinstance(request_payload, dict):
            await websocket.close(code=1008, reason="El payload debe ser un objeto JSON")
            return
        try:
            payload = BuildContextRequest.model_validate(request_payload)
        except ValidationError:
            await websocket.close(code=1008, reason="Payload inválido")
            return

        try:
            documents = await _gather_converted_documents(project)
            existing_context = await _load_existing_context_or_none(project)
            output_folder_name = _resolve_output_folder_name(existing_context, payload.output_folder_name)
        except HTTPException as exc:
            await websocket.close(code=1008, reason=str(exc.detail))
            return

        async def on_ai_progress(index: int, total: int, path: str) -> None:
            await websocket.send_json(
                ContextBuildEvent(event=ContextBuildEventType.AI_DOCUMENT_CLASSIFIED, data={"index": index, "total": total, "path": path}).model_dump(
                    mode="json"
                )
            )

        async def on_document_copied(index: int, total: int, path: str) -> None:
            await websocket.send_json(
                ContextBuildEvent(event=ContextBuildEventType.DOCUMENT_COPIED, data={"index": index, "total": total, "path": path}).model_dump(
                    mode="json"
                )
            )

        context: Context | None = None
        try:
            async with _optional_ai_client(payload.ai_classification_enabled) as ai_client:
                # `_optional_ai_client` resuelve la config de LiteLLM (y puede lanzar
                # `HTTPException`) ANTES de emitir "started" -- evita que el semáforo
                # llegue a mostrar "iniciando..." para acto seguido cerrarse en error.
                await websocket.send_json(ContextBuildEvent(event=ContextBuildEventType.STARTED, data={}).model_dump(mode="json"))
                if ai_client is not None:
                    await websocket.send_json(ContextBuildEvent(event=ContextBuildEventType.AI_CLASSIFYING_STARTED, data={}).model_dump(mode="json"))
                context = await _context_builder.build(
                    project,
                    documents,
                    candidate_domains=payload.candidate_domains,
                    threshold=payload.threshold,
                    ai_classification_enabled=payload.ai_classification_enabled,
                    ai_classification_client=ai_client,
                    output_folder_name=output_folder_name,
                    on_ai_progress=on_ai_progress,
                )
                total_documents = sum(len(domain.documents) for domain in context.domains)
                await websocket.send_json(
                    ContextBuildEvent(event=ContextBuildEventType.REORGANIZE_STARTED, data={"total": total_documents}).model_dump(mode="json")
                )
                await _reorganizer.reorganize(project, context, on_document_copied=on_document_copied)
                context.reorganized = True
                await websocket.send_json(ContextBuildEvent(event=ContextBuildEventType.MKDOCS_STARTED, data={}).model_dump(mode="json"))
                _, site_built = await _mkdocs_generator.generate(project, context)
                context.mkdocs_generated = True
                context.mkdocs_site_built = site_built
        except HTTPException as exc:
            await websocket.close(code=1008, reason=str(exc.detail))
            return
        except WebSocketDisconnect:
            logger.info(f"Cliente desconectado durante la construcción del contexto de '{name}' (tenant '{tenant_id}')")
            return
        finally:
            # Igual que `build_context()` (REST): si `reorganize()`/`generate()` fallan
            # o el cliente se desconecta a mitad, `context.json` se persiste igualmente
            # con los flags que reflejan lo que de verdad se completó.
            if context is not None:
                await _context_registry.save_context(project, context)

        await websocket.send_json(
            ContextBuildEvent(event=ContextBuildEventType.COMPLETED, data=_to_response(context).model_dump(mode="json")).model_dump(mode="json")
        )
        await websocket.close()
    finally:
        release_project_operation_lock(websocket, operation_key)


@router.websocket("/api/projects/{name}/context/delete")
async def context_delete_websocket(name: str, websocket: WebSocket) -> None:
    """Elimina el contexto de `name`, retransmitiendo progreso (semáforo) como
    `ContextDeleteEvent` JSON — equivalente en efectos a `delete_context_endpoint()`
    (REST). Solo 3 pasos macro (sin bucles por documento que reportar), a
    diferencia de `context_build_websocket`.
    """
    await websocket.accept()

    auth_result = await authorize_project_websocket(websocket, name)
    if auth_result is None:
        return
    tenant_id, _allowed_scan_roots = auth_result  # construir/eliminar contexto no acepta rutas de filesystem del cliente

    operation_key = await acquire_project_operation_lock(websocket, tenant_id, name)
    if operation_key is None:
        return
    try:
        async with get_project_registry(websocket) as registry:
            try:
                project = await registry.get_project(name, tenant_id=tenant_id)
            except ProjectNotFoundError:
                await websocket.close(code=1008, reason="Project not found")
                return

        try:
            request_payload = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await websocket.close(code=1008, reason="El payload debe ser JSON válido")
            return
        if not isinstance(request_payload, dict) or request_payload.get("confirm") is not True:
            await websocket.close(code=1008, reason="Se requiere confirmación explícita para eliminar el contexto.")
            return

        try:
            context = await _context_registry.load_context(project)
        except ContextNotFoundError:
            await websocket.close(code=1008, reason="El proyecto no tiene contexto construido.")
            return

        try:
            await websocket.send_json(ContextDeleteEvent(event=ContextDeleteEventType.STARTED, data={}).model_dump(mode="json"))
            # Limpieza física antes de borrar context.json: mismo orden defensivo que
            # `delete_context_endpoint` (REST) — si algo falla a mitad, context.json
            # sigue existiendo como fuente de verdad de qué queda por limpiar.
            await _reorganizer.delete_output(project, context)
            await websocket.send_json(ContextDeleteEvent(event=ContextDeleteEventType.OUTPUT_DELETED, data={}).model_dump(mode="json"))
            await _mkdocs_generator.delete_site(project)
            await websocket.send_json(ContextDeleteEvent(event=ContextDeleteEventType.SITE_DELETED, data={}).model_dump(mode="json"))
            await _context_registry.delete_context(project)
            await websocket.send_json(ContextDeleteEvent(event=ContextDeleteEventType.COMPLETED, data={}).model_dump(mode="json"))
        except WebSocketDisconnect:
            logger.info(f"Cliente desconectado durante la eliminación del contexto de '{name}' (tenant '{tenant_id}')")
            return
        await websocket.close()
    finally:
        release_project_operation_lock(websocket, operation_key)


def _is_litellm_classification_configured() -> bool:
    # Solo lee variables de entorno (sin red) — mismo chequeo que hace
    # `_optional_ai_client` al construir el contexto, pero aquí solo para
    # informar en la UI si el proxy de clasificación está listo o no.
    try:
        litellm_classification_config_from_env()
    except ValueError:
        return False
    return True


@router.get("/projects/{name}/context", response_class=HTMLResponse, dependencies=[Depends(require_project_access)])
async def context_page(name: str, request: Request) -> HTMLResponse:
    project = await _get_project(request, name)
    context = await _load_existing_context_or_none(project)
    litellm_configured = _is_litellm_classification_configured()
    return _templates.TemplateResponse(
        request,
        "context.html.j2",
        {"project": project, "context": context, "litellm_configured": litellm_configured, "default_output_folder_name": _DEFAULT_OUTPUT_FOLDER_NAME},
    )


async def _load_built_context(request: Request, name: str) -> Path:
    """Resuelve `site_root` para servir el sitio MkDocs ya construido de `name` —
    usado por `context_site_index`/`context_site_asset`, nunca por el flujo de
    build (`build_context`/`context_build_websocket`): visualizar el sitio es una
    acción de solo lectura totalmente independiente de generarlo.

    Raises:
        HTTPException: 404 si el proyecto no tiene contexto construido, o si la
            última construcción no dejó un sitio navegable (`mkdocs_site_built`
            en `False` — ver `MkDocsGenerator._build_site`).
    """
    project = await _get_project(request, name)
    context = await _load_existing_context_or_none(project)
    if context is None or not context.mkdocs_site_built:
        raise HTTPException(status_code=404, detail="El proyecto no tiene un sitio de documentación construido.")
    return (Path(project.root_path) / _SITE_DIR_NAME).resolve()


@router.get("/projects/{name}/context/site", dependencies=[Depends(require_project_access)])
async def context_site_index(name: str, request: Request) -> RedirectResponse:
    """Redirige a la versión con barra final (`.../site/`): las páginas que genera
    mkdocs usan URLs relativas (CSS/JS/enlaces de navegación) que asumen que el
    índice se sirve en una ruta terminada en '/' (`use_directory_urls`, activo por
    defecto — ver `MkDocsGenerator._build_config`); sin la barra, esos enlaces
    relativos resolverían un nivel por encima del sitio.
    """
    await _load_built_context(request, name)
    return RedirectResponse(url=f"{request.url.path}/")


@router.get("/projects/{name}/context/site/{file_path:path}", response_model=None, dependencies=[Depends(require_project_access)])
async def context_site_asset(name: str, file_path: str, request: Request) -> FileResponse | RedirectResponse:
    """Sirve un fichero del sitio MkDocs ya construido de `name`, bajo `site/{file_path}`.

    Si `file_path` resuelve a un directorio (páginas de mkdocs con
    `use_directory_urls`) y la petición no terminaba en '/', redirige añadiéndola
    (mismo motivo que `context_site_index`); si ya terminaba en '/', sirve el
    `index.html` de ese directorio.

    Raises:
        HTTPException: 404 si no hay sitio construido (ver `_load_built_context`),
            o si `file_path` no resuelve a nada dentro de `site/` — incluye
            cualquier intento de escapar de ese directorio vía `..`.
    """
    site_root = await _load_built_context(request, name)
    target = (site_root / file_path).resolve()
    if not target.is_relative_to(site_root):
        raise HTTPException(status_code=404, detail="Recurso no encontrado en el sitio de documentación.")

    if await asyncio.to_thread(target.is_dir):
        if not request.url.path.endswith("/"):
            return RedirectResponse(url=f"{request.url.path}/")
        target = target / _SITE_INDEX_NAME

    if not await asyncio.to_thread(target.is_file):
        raise HTTPException(status_code=404, detail="Recurso no encontrado en el sitio de documentación.")
    return FileResponse(target)


__all__ = ["router"]
