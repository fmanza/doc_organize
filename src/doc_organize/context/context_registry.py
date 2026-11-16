"""
Persistencia plana del contexto de organización documental de un proyecto.
"""

import asyncio
import json

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from doc_organize.core.constants import CONTEXT_FILE_NAME, DOMAINS_FOLDER_NAME, UNCLASSIFIED_FILE_NAME
from doc_organize.core.exceptions import ContextError, ContextNotFoundError, DomainNotFoundError
from doc_organize.core.models import Context, Domain, DomainDocument, Project, UnclassifiedDocument
from doc_organize.utils.atomic_write import write_text_atomic
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import remove_tree

_CONTEXT_FILE_NAME = CONTEXT_FILE_NAME
_DOMAINS_DIR_NAME = DOMAINS_FOLDER_NAME
_DOMAIN_MD_NAME = "DOMAIN.md"
_DOMAIN_INDEX_NAME = "index.json"
_DOMAIN_DOCUMENTS_HEADING = "## Documentos clasificados"


async def _read_json_object(path: Path, what: str) -> dict[str, Any]:
    """Objeto JSON de `path`; cualquier fallo de lectura o de forma, como `ContextError` (1.5.0).

    Antes, un fichero que no era UTF-8 o un JSON válido que no era un objeto (`[]`) salían como `UnicodeDecodeError` o
    `TypeError`, que el llamador no podía distinguir de un fallo de programación.
    """
    try:
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextError(f"{what} está corrupto o no se puede leer: {path}") from exc
    if not isinstance(payload, dict):
        raise ContextError(f"{what} está corrupto (no es un objeto JSON): {path}")
    return payload


class ContextRegistry:
    """Lee y escribe el contexto de un proyecto: `context.json` + `domains/<slug>/{DOMAIN.md,index.json}` +
    `unclassified.json` (1.6.0).

    `unclassified.json` guarda `Context.unclassified_details`, aparte para que `context.json` siga siendo pequeño. Se
    escribe antes que `context.json`. Al leer, `context.json` manda: se conservan los detalles cuya ruta está en
    `unclassified_documents`, en su orden, y si sobran o faltan (un guardado que se cortó entre los dos ficheros, o un
    consumidor que editó `unclassified_documents`) se avisa. Un contexto anterior a 1.6.0, sin el fichero, se carga con
    `unclassified_details=[]` sin aviso.

    Mismo patrón de concurrencia que `ProjectRegistry`/`ScannedFoldersStore`: un
    `asyncio.Lock` en proceso + escritura atómica (fichero temporal + `os.replace`)
    por fichero tocado. `context.json` guarda metadatos + un resumen de cada
    dominio (sin la lista de documentos, que vive aparte en `index.json` por
    dominio — evita un `context.json` que crezca sin límite con proyectos grandes).

    `DOMAIN.md` se regenera solo en su sección "## Documentos clasificados": si el
    fichero ya existe, todo lo anterior a esa cabecera (Descripción, Alcance, Tipos
    esperados — texto libre editado a mano) se conserva tal cual.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from datetime import UTC, datetime
        >>> from pathlib import Path
        >>> from doc_organize.core.models import Context, Domain, Project
        >>> async def main():
        ...     root = tempfile.mkdtemp()
        ...     project = Project(name="Demo", root_path=root, created_at=datetime.now(UTC).isoformat())
        ...     context = Context(
        ...         project_name=project.name,
        ...         domains=[Domain(slug="ciberseguridad", name="Ciberseguridad")],
        ...         created_at=datetime.now(UTC).isoformat(),
        ...         updated_at=datetime.now(UTC).isoformat(),
        ...     )
        ...     registry = ContextRegistry()
        ...     await registry.save_context(project, context)
        ...     loaded = await registry.load_context(project)
        ...     return loaded.domains[0].slug
        >>> asyncio.run(main())
        'ciberseguridad'
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._lock = asyncio.Lock()

    async def load_context(self, project: Project) -> Context:
        """Carga el contexto de `project`.

        Raises:
            ContextNotFoundError: Si el proyecto no tiene `context.json` todavía.
            ContextError: Si `context.json`, `unclassified.json` o algún `index.json` de dominio está corrupto, o si
                `output_folder_name` no es un nombre de carpeta válido ("..", una ruta absoluta, un nombre
                reservado...; L-8f): nunca se devuelve un contexto que copiaría o borraría fuera de su sitio.
        """
        async with self._lock:
            return await self._load(project)

    async def save_context(self, project: Project, context: Context) -> None:
        """Persiste `context`: `context.json` + un `index.json`/`DOMAIN.md` por dominio."""
        async with self._lock:
            await self._save(project, context)

    async def delete_context(self, project: Project) -> None:
        """Borra `context.json`, `unclassified.json` y `domains/` de `project`, si existen.

        Idempotente (no falla si ya no hay nada que borrar) — igual criterio que
        una operación DELETE HTTP.
        """
        async with self._lock:
            await asyncio.to_thread(self._context_path(project).unlink, missing_ok=True)
            await asyncio.to_thread(self._unclassified_path(project).unlink, missing_ok=True)
            domains_root = Path(project.root_path) / _DOMAINS_DIR_NAME
            if await asyncio.to_thread(domains_root.is_dir):
                await asyncio.to_thread(remove_tree, domains_root)

    async def get_domain(self, project: Project, slug: str) -> Domain:
        """Devuelve el dominio `slug` del contexto de `project`.

        Raises:
            ContextNotFoundError: Si el proyecto no tiene contexto todavía.
            DomainNotFoundError: Si no hay ningún dominio con ese slug.
        """
        async with self._lock:
            context = await self._load(project, with_unclassified=False)  # el detalle de los sin clasificar no hace falta
        domain = next((d for d in context.domains if d.slug == slug), None)
        if domain is None:
            raise DomainNotFoundError(f"No hay ningún dominio '{slug}' en el contexto de '{project.name}'.")
        return domain

    def _context_path(self, project: Project) -> Path:
        return Path(project.root_path) / _CONTEXT_FILE_NAME

    def _unclassified_path(self, project: Project) -> Path:
        return Path(project.root_path) / UNCLASSIFIED_FILE_NAME

    def _domain_dir(self, project: Project, slug: str) -> Path:
        return Path(project.root_path) / _DOMAINS_DIR_NAME / slug

    async def _load(self, project: Project, *, with_unclassified: bool = True) -> Context:
        context_path = self._context_path(project)
        if not context_path.exists():
            raise ContextNotFoundError(f"El proyecto '{project.name}' no tiene contexto construido todavía.")

        payload = await _read_json_object(context_path, "El contexto del proyecto")

        domain_summaries = payload.pop("domains", [])
        if not isinstance(domain_summaries, list):
            raise ContextError(f"El contexto del proyecto está corrupto ('domains' no es una lista): {context_path}")
        domains = []
        for summary in domain_summaries:
            if not isinstance(summary, dict) or not isinstance(summary.get("slug"), str):
                raise ContextError(f"El contexto del proyecto está corrupto (dominio sin 'slug'): {context_path}")
            slug = summary["slug"]

            documents = await self._load_domain_documents(project, slug)
            try:
                domains.append(Domain(**summary, documents=documents))
            except ValidationError as exc:
                raise ContextError(f"El resumen del dominio '{slug}' está corrupto: {context_path}") from exc

        payload.pop("unclassified_details", None)  # vive en unclassified.json, nunca en context.json
        try:
            context = Context(**payload, domains=domains)
        except ValidationError as exc:
            if any(error["loc"][:1] == ("output_folder_name",) for error in exc.errors()):
                raise ContextError(f"El contexto del proyecto tiene un 'output_folder_name' inválido: {context_path}") from exc
            raise ContextError(f"El contexto del proyecto está corrupto: {context_path}") from exc
        if with_unclassified:
            context.unclassified_details = await self._load_unclassified(project, context.unclassified_documents)
        return context

    async def _load_unclassified(self, project: Project, unclassified_documents: list[str]) -> list[UnclassifiedDocument]:
        path = self._unclassified_path(project)
        if not await asyncio.to_thread(path.exists):
            return []
        payload = await _read_json_object(path, "El detalle de los documentos sin clasificar")
        entries = payload.get("documents", [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ContextError(f"El detalle de los documentos sin clasificar está corrupto ('documents' no es una lista de objetos): {path}")
        try:
            details = [UnclassifiedDocument(**entry) for entry in entries]
        except ValidationError as exc:
            raise ContextError(f"El detalle de los documentos sin clasificar está corrupto: {path}") from exc
        if not details:  # guardado sin detalle (un `Context` creado a mano): nada que alinear
            return []
        by_path = {detail.source_path: detail for detail in details}
        aligned = [by_path[source_path] for source_path in unclassified_documents if source_path in by_path]
        if len(aligned) != len(details) or len(aligned) != len(unclassified_documents):
            self.logger.warning(
                f"'{path}' no coincide con 'unclassified_documents' de context.json (¿guardado interrumpido o contexto "
                f"editado?): se conservan {len(aligned)} de {len(unclassified_documents)} detalles"
            )
        return aligned

    async def _load_domain_documents(self, project: Project, slug: str) -> list[DomainDocument]:
        index_path = self._domain_dir(project, slug) / _DOMAIN_INDEX_NAME
        if not index_path.exists():
            return []
        payload = await _read_json_object(index_path, f"El índice del dominio '{slug}'")
        entries = payload.get("documents", [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ContextError(f"El índice del dominio '{slug}' está corrupto ('documents' no es una lista de objetos): {index_path}")
        try:
            return [DomainDocument(**entry) for entry in entries]
        except ValidationError as exc:
            raise ContextError(f"El índice del dominio '{slug}' está corrupto: {index_path}") from exc

    async def _save(self, project: Project, context: Context) -> None:
        context_path = self._context_path(project)
        await asyncio.to_thread(context_path.parent.mkdir, parents=True, exist_ok=True)

        unclassified_payload = {"documents": [document.model_dump() for document in context.unclassified_details]}
        await self._write_json_atomic(self._unclassified_path(project), unclassified_payload)  # antes que context.json

        payload = context.model_dump(exclude={"domains", "unclassified_details"})
        payload["domains"] = [
            {
                "slug": domain.slug,
                "name": domain.name,
                "description": domain.description,
                "status": domain.status.value,
                "predefined": domain.predefined,
            }
            for domain in context.domains
        ]
        await self._write_json_atomic(context_path, payload)

        current_slugs = {domain.slug for domain in context.domains}
        await self._remove_stale_domain_dirs(project, current_slugs)

        for domain in context.domains:
            await self._save_domain(project, domain)

    async def _remove_stale_domain_dirs(self, project: Project, current_slugs: set[str]) -> None:
        """Borra `domains/<slug>/` de dominios que ya no están en la última reconstrucción.

        Sin esto, un dominio presente en un `build()` anterior pero ausente del
        actual queda huérfano en disco: invisible desde `context.json` (que solo
        lista los dominios actuales) pero ocupando espacio indefinidamente.
        """
        domains_root = Path(project.root_path) / _DOMAINS_DIR_NAME
        if not domains_root.is_dir():
            return
        stale_dirs = await asyncio.to_thread(self._list_stale_domain_dirs, domains_root, current_slugs)
        for stale_dir in stale_dirs:
            await asyncio.to_thread(remove_tree, stale_dir)
            self.logger.info(f"Dominio obsoleto eliminado tras reconstruir el contexto: {stale_dir}")

    @staticmethod
    def _list_stale_domain_dirs(domains_root: Path, current_slugs: set[str]) -> list[Path]:
        return [entry for entry in domains_root.iterdir() if entry.is_dir() and entry.name not in current_slugs]

    async def _save_domain(self, project: Project, domain: Domain) -> None:
        domain_dir = self._domain_dir(project, domain.slug)
        await asyncio.to_thread(domain_dir.mkdir, parents=True, exist_ok=True)

        index_payload = {"documents": [document.model_dump() for document in domain.documents]}
        await self._write_json_atomic(domain_dir / _DOMAIN_INDEX_NAME, index_payload)
        await self._write_domain_md(domain_dir / _DOMAIN_MD_NAME, domain)

    async def _write_domain_md(self, md_path: Path, domain: Domain) -> None:
        documents_section = self._render_documents_section(domain)
        if md_path.exists():
            existing = await asyncio.to_thread(md_path.read_text, encoding="utf-8")
            head = existing.split(_DOMAIN_DOCUMENTS_HEADING, 1)[0].rstrip()
            content = f"{head}\n\n{documents_section}\n"
        else:
            content = self._render_new_domain_md(domain, documents_section)
        await self._write_text_atomic(md_path, content)

    @staticmethod
    def _render_documents_section(domain: Domain) -> str:
        lines = [_DOMAIN_DOCUMENTS_HEADING, "<!-- generado desde index.json, no editar a mano -->", ""]
        if not domain.documents:
            lines.append("*No aplica a este dominio.*")
        else:
            lines.extend(f"- `{document.title}` ({document.document_type}) — {document.source_path}" for document in domain.documents)
        return "\n".join(lines)

    @staticmethod
    def _render_new_domain_md(domain: Domain, documents_section: str) -> str:
        return (
            f"---\n"
            f"domain: {domain.slug}\n"
            f"status: {domain.status.value}\n"
            f"document_count: {len(domain.documents)}\n"
            f"---\n\n"
            f"# Dominio: {domain.name}\n\n"
            f"## Descripción\n*No aplica a este dominio.*\n\n"
            f"## Alcance (qué SÍ / qué NO)\n*No aplica a este dominio.*\n\n"
            f"## Tipos de documento esperados\n*No aplica a este dominio.*\n\n"
            f"{documents_section}\n"
        )

    @staticmethod
    async def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        await ContextRegistry._write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False))

    @staticmethod
    async def _write_text_atomic(path: Path, content: str) -> None:
        # L-8e (G31): temporal con nombre aleatorio y creado en exclusiva, nunca `<fichero>.tmp` de nombre fijo.
        await asyncio.to_thread(write_text_atomic, path, content)


__all__ = ["ContextRegistry"]
