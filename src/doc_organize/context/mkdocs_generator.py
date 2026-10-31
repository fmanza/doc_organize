"""
Generación de la configuración MkDocs del sitio de un proyecto.
"""

import asyncio
import shutil
import subprocess

from pathlib import Path
from typing import Any

import yaml

from doc_organize.context.reorganizer import resolve_document_slug_parts
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_INDEX_MD_NAME = "index.md"
_MKDOCS_YML_NAME = "mkdocs.yml"
_SITE_DIR_NAME = "site"


class MkDocsGenerator:
    """Genera `mkdocs.yml` + `index.md` para navegar el contenido ya reorganizado de un proyecto.

    Usa directamente `<output_folder_name>/` (ya poblada por `Reorganizer`) como
    `docs_dir` de MkDocs — no copia el contenido una segunda vez (evitaría una
    cuarta copia: original -> `converter/` -> `organizado/` -> aquí). Nav
    generado agrupando por dominio; cada entrada apunta al `.md` ya copiado.

    Requiere el extra `doc_organize[context]` (`pyyaml`). Tras escribir la
    configuración, intenta además `mkdocs build` (subprocess) hacia `site/` para
    dejar un sitio ya navegable en disco — `mkdocs` no es una dependencia dura de
    este extra (solo vive en el extra `docs`, para la documentación de la propia
    librería), así que si no está instalado en el entorno simplemente se deja
    escrito `mkdocs.yml` (igual que antes) y `Context.mkdocs_site_built` queda en
    `False`: nunca un `ImportError`/excepción críptica por una dependencia
    opcional que falta.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self) -> None:
        self.logger = logger

    async def generate(self, project: Project, context: Context) -> tuple[Path, bool]:
        """Escribe `mkdocs.yml` (raíz del proyecto) + `<output_folder_name>/index.md`,
        y ejecuta `mkdocs build` si `mkdocs` está disponible en el entorno.

        Returns:
            `(mkdocs_yml_path, site_built)` — `site_built` es `False` si `mkdocs`
            no está instalado o si `mkdocs build` termina con error (el fallo se
            loguea pero no se propaga: `mkdocs.yml` + la copia ya reorganizada
            siguen siendo útiles aunque el build del sitio falle).
        """
        output_root = Path(project.root_path) / context.output_folder_name
        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        await self._write_index(output_root, context)

        mkdocs_yml_path = Path(project.root_path) / _MKDOCS_YML_NAME
        config = self._build_config(project, context)
        content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        await asyncio.to_thread(mkdocs_yml_path.write_text, content, encoding="utf-8")

        site_built = await self._build_site(project, mkdocs_yml_path)
        return mkdocs_yml_path, site_built

    def _build_config(self, project: Project, context: Context) -> dict[str, Any]:
        nav: list[Any] = [{"Inicio": _INDEX_MD_NAME}]
        for domain in context.domains:
            domain_nav = self._build_domain_nav(domain, context.taxonomy_manifest_used)
            if domain_nav:
                nav.append({domain.name: domain_nav})
        return {
            "site_name": f"{project.name} — Documentación organizada",
            "docs_dir": context.output_folder_name,
            "site_dir": _SITE_DIR_NAME,
            "nav": nav,
        }

    def _build_domain_nav(self, domain: Domain, taxonomy_manifest_used: bool) -> list[Any]:
        """Nav de un dominio: lista plana de documentos (modo sin manifiesto), o agrupada
        por `material_type` dentro del dominio cuando `taxonomy_manifest_used` — mismo
        criterio de profundidad `dominio > tipo de material > documentos` que la carpeta
        física (`Reorganizer`, vía `resolve_document_slug_parts`)."""
        if not taxonomy_manifest_used:
            return [{document.title: self._relative_doc_path(domain, document)} for document in domain.documents]

        by_material_type: dict[str, list[DomainDocument]] = {}
        for document in domain.documents:
            material_type = document.material_type or "sin-clasificar"
            by_material_type.setdefault(material_type, []).append(document)

        nav: list[Any] = []
        for material_type, docs in by_material_type.items():
            entries = [{document.title: self._relative_doc_path(domain, document)} for document in docs]
            # `material_type_name` (nombre legible del manifiesto) es el mismo para todos los
            # documentos de este grupo -- comparten `material_type`, luego la misma entrada del
            # catálogo `TaxonomyManifest.material_types`. `None` para el placeholder "sin-clasificar"
            # (sin entrada en el manifiesto) o en modo sin manifiesto: cae al fallback derivado del
            # slug, igual que antes (AUDIT_CODE: antes de esto, la etiqueta siempre se derivaba del
            # slug, ignorando el `name` declarado en el manifiesto).
            label = docs[0].material_type_name or material_type.replace("-", " ").title()
            nav.append({label: entries})
        return nav

    async def _build_site(self, project: Project, mkdocs_yml_path: Path) -> bool:
        mkdocs_bin = await asyncio.to_thread(shutil.which, "mkdocs")
        if mkdocs_bin is None:
            self.logger.warning(
                f"mkdocs no está instalado en este entorno (extra 'site') — '{mkdocs_yml_path}' escrito, pero sin sitio navegable en disco."
            )
            return False

        result = await asyncio.to_thread(
            subprocess.run,
            [mkdocs_bin, "build", "--clean", "-f", str(mkdocs_yml_path)],
            cwd=project.root_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            self.logger.warning(f"'mkdocs build' falló para '{project.name}' (código {result.returncode}): {result.stderr.strip()}")
            return False
        return True

    async def delete_site(self, project: Project) -> None:
        """Borra `mkdocs.yml` y `site/` de `project.root_path`, si existen.

        Usado al eliminar el contexto de un proyecto para volver al estado
        anterior a la primera construcción (ver `web/routes/context.py`).
        """
        mkdocs_yml_path = Path(project.root_path) / _MKDOCS_YML_NAME
        site_dir = Path(project.root_path) / _SITE_DIR_NAME
        await asyncio.to_thread(mkdocs_yml_path.unlink, missing_ok=True)
        if await asyncio.to_thread(site_dir.is_dir):
            await asyncio.to_thread(shutil.rmtree, site_dir)

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
