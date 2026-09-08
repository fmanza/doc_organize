"""
Persistencia plana del contexto de organización documental de un proyecto.
"""

import asyncio
import json
import os
import shutil

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from doc_organize.core.exceptions import ContextError, ContextNotFoundError, DomainNotFoundError
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.utils.logging import get_logger

_CONTEXT_FILE_NAME = "context.json"
_DOMAINS_DIR_NAME = "domains"
_DOMAIN_MD_NAME = "DOMAIN.md"
_DOMAIN_INDEX_NAME = "index.json"
_DOMAIN_DOCUMENTS_HEADING = "## Documentos clasificados"


class ContextRegistry:
    """Lee y escribe el contexto de un proyecto: `context.json` + `domains/<slug>/{DOMAIN.md,index.json}`.

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
            ContextError: Si `context.json` o algún `index.json` de dominio está corrupto.
        """
        async with self._lock:
            return await self._load(project)

    async def save_context(self, project: Project, context: Context) -> None:
        """Persiste `context`: `context.json` + un `index.json`/`DOMAIN.md` por dominio."""
        async with self._lock:
            await self._save(project, context)

    async def get_domain(self, project: Project, slug: str) -> Domain:
        """Devuelve el dominio `slug` del contexto de `project`.

        Raises:
            ContextNotFoundError: Si el proyecto no tiene contexto todavía.
            DomainNotFoundError: Si no hay ningún dominio con ese slug.
        """
        context = await self.load_context(project)
        domain = next((d for d in context.domains if d.slug == slug), None)
        if domain is None:
            raise DomainNotFoundError(f"No hay ningún dominio '{slug}' en el contexto de '{project.name}'.")
        return domain

    def _context_path(self, project: Project) -> Path:
        return Path(project.root_path) / _CONTEXT_FILE_NAME

    def _domain_dir(self, project: Project, slug: str) -> Path:
        return Path(project.root_path) / _DOMAINS_DIR_NAME / slug

    async def _load(self, project: Project) -> Context:
        context_path = self._context_path(project)
        if not context_path.exists():
            raise ContextNotFoundError(f"El proyecto '{project.name}' no tiene contexto construido todavía.")

        raw = await asyncio.to_thread(context_path.read_text, encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContextError(f"El contexto del proyecto está corrupto: {context_path}") from exc

        domain_summaries = payload.pop("domains", [])
        domains = []
        for summary in domain_summaries:
            try:
                slug = summary["slug"]
            except KeyError as exc:
                raise ContextError(f"El contexto del proyecto está corrupto (dominio sin 'slug'): {context_path}") from exc

            documents = await self._load_domain_documents(project, slug)
            try:
                domains.append(Domain(**summary, documents=documents))
            except ValidationError as exc:
                raise ContextError(f"El resumen del dominio '{slug}' está corrupto: {context_path}") from exc

        try:
            return Context(**payload, domains=domains)
        except ValidationError as exc:
            raise ContextError(f"El contexto del proyecto está corrupto: {context_path}") from exc

    async def _load_domain_documents(self, project: Project, slug: str) -> list[DomainDocument]:
        index_path = self._domain_dir(project, slug) / _DOMAIN_INDEX_NAME
        if not index_path.exists():
            return []
        raw = await asyncio.to_thread(index_path.read_text, encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContextError(f"El índice del dominio '{slug}' está corrupto: {index_path}") from exc
        try:
            return [DomainDocument(**entry) for entry in payload.get("documents", [])]
        except ValidationError as exc:
            raise ContextError(f"El índice del dominio '{slug}' está corrupto: {index_path}") from exc

    async def _save(self, project: Project, context: Context) -> None:
        context_path = self._context_path(project)
        await asyncio.to_thread(context_path.parent.mkdir, parents=True, exist_ok=True)

        payload = context.model_dump(exclude={"domains"})
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
            await asyncio.to_thread(shutil.rmtree, stale_dir)
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
        tmp_path = path.with_suffix(".tmp")
        await asyncio.to_thread(tmp_path.write_text, content, encoding="utf-8")
        await asyncio.to_thread(os.replace, tmp_path, path)


__all__ = ["ContextRegistry"]
