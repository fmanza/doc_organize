"""
Generación de la configuración MkDocs del sitio de un proyecto.
"""

import asyncio

from pathlib import Path
from typing import Any

import yaml

from doc_organize.context.reorganizer import resolve_document_slug_parts
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_INDEX_MD_NAME = "index.md"
_MKDOCS_YML_NAME = "mkdocs.yml"


class MkDocsGenerator:
    """Genera `mkdocs.yml` + `index.md` para navegar el contenido ya reorganizado de un proyecto.

    Usa directamente `<output_folder_name>/` (ya poblada por `Reorganizer`) como
    `docs_dir` de MkDocs — no copia el contenido una segunda vez (evitaría una
    cuarta copia: original -> `converter/` -> `organizado/` -> aquí). Nav
    generado agrupando por dominio; cada entrada apunta al `.md` ya copiado.

    Requiere el extra `doc_organize[context]` (`pyyaml`). No ejecuta
    `mkdocs build`: solo escribe la configuración — construir el sitio de verdad
    (con MkDocs instalado aparte) es responsabilidad del usuario.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self) -> None:
        self.logger = logger

    async def generate(self, project: Project, context: Context) -> Path:
        """Escribe `mkdocs.yml` (raíz del proyecto) + `<output_folder_name>/index.md`.

        Returns:
            Ruta al `mkdocs.yml` generado.
        """
        output_root = Path(project.root_path) / context.output_folder_name
        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        await self._write_index(output_root, context)

        mkdocs_yml_path = Path(project.root_path) / _MKDOCS_YML_NAME
        config = self._build_config(project, context)
        content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        await asyncio.to_thread(mkdocs_yml_path.write_text, content, encoding="utf-8")
        return mkdocs_yml_path

    def _build_config(self, project: Project, context: Context) -> dict[str, Any]:
        nav: list[Any] = [{"Inicio": _INDEX_MD_NAME}]
        for domain in context.domains:
            entries = [{document.title: self._relative_doc_path(domain, document)} for document in domain.documents]
            if entries:
                nav.append({domain.name: entries})
        return {
            "site_name": f"{project.name} — Documentación organizada",
            "docs_dir": context.output_folder_name,
            "nav": nav,
        }

    @staticmethod
    def _relative_doc_path(domain: Domain, document: DomainDocument) -> str:
        # Con "/" literales, nunca `Path` (en Windows uniría con "\\", rompiendo
        # el `nav` de mkdocs.yml) — misma fórmula que usa `Reorganizer` para el
        # destino real en disco, via `resolve_document_slug_parts` compartida.
        document_type, stem = resolve_document_slug_parts(document)
        return f"{domain.slug}/{document_type}/{stem}/{stem}.md"

    async def _write_index(self, output_root: Path, context: Context) -> None:
        lines = [f"# {context.project_name} — Documentación organizada", ""]
        if not context.domains:
            lines.append("*No aplica: todavía no hay dominios clasificados.*")
        else:
            lines.extend(f"- **{domain.name}** ({len(domain.documents)} documento(s))" for domain in context.domains)
        content = "\n".join(lines) + "\n"
        await asyncio.to_thread((output_root / _INDEX_MD_NAME).write_text, content, encoding="utf-8")


__all__ = ["MkDocsGenerator"]
