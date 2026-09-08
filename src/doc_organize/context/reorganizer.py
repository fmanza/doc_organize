"""
Copia física de los documentos clasificados a la carpeta reorganizada del proyecto.
"""

import asyncio
import shutil

from pathlib import Path

from doc_organize.core.exceptions import IncompleteConversionArtifactsError
from doc_organize.core.models import Context, DomainDocument, Project
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)


def resolve_document_slug_parts(document: DomainDocument) -> tuple[str, str]:
    """`(document_type, stem)`: determina la carpeta de un documento clasificado
    bajo `<output_folder_name>/<dominio>/<tipo>/<stem>/`.

    Compartida entre `Reorganizer` (ruta real en disco) y `MkDocsGenerator` (ruta
    del `.md` en el `nav` de `mkdocs.yml`, siempre con `/` literales — nunca
    `Path`, que en Windows usaría `\\`) — antes cada uno repetía
    `Path(document.markdown_path).stem` por su cuenta, sin nada que garantizara
    que no divergieran (AUDIT_CODE, sesión 2026-09-09).
    """
    stem = Path(document.markdown_path).stem
    return document.document_type, stem


class Reorganizer:
    """Copia el original + `.md` + `.json` de cada documento clasificado a `<output_folder_name>/`.

    Destino: `<project.root_path>/<context.output_folder_name>/<dominio>/<tipo>/<stem>/`,
    con los tres artefactos dentro (original, `.md`, `.json`) — nunca solo uno (ver
    `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md` §1/§4).
    Copia, nunca mueve: la fuente original no se toca.

    A diferencia de `DomainClassifier` (Level 1), que manda en silencio a "sin
    clasificar" un documento con artefactos incompletos, aquí SÍ es un error: si
    `Context` dice que un documento está clasificado, sus tres rutas deben existir
    de verdad en disco para poder copiarlo — de ahí `IncompleteConversionArtifactsError`.

    Limitación conocida: si dos documentos del mismo dominio/tipo comparten el
    mismo `stem` (p. ej. dos ficheros distintos ambos llamados `informe.pdf` en
    carpetas de origen distintas), el segundo sobrescribe el primero en
    `<stem>/` — no hay desambiguación todavía.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self) -> None:
        self.logger = logger

    async def reorganize(self, project: Project, context: Context) -> Path:
        """Copia todos los documentos clasificados de `context` a la carpeta de salida.

        Valida que los tres artefactos de **todos** los documentos existan en
        disco antes de borrar o copiar nada — si alguno falta, se levanta
        `IncompleteConversionArtifactsError` sin haber tocado una sola carpeta.
        Sin esta validación previa, un documento roto a mitad del lote podía
        hacer que ya se hubiera borrado la carpeta de un dominio (para
        reconstruirla) antes de descubrir el fallo, perdiendo copias válidas de
        una reconstrucción anterior sin posibilidad de recuperarlas
        (AUDIT_CODE, sesión 2026-09-09).

        Solo después de validar: borra la carpeta de cada dominio actual (se
        reconstruye entera) y la de cualquier dominio ya no presente en
        `context` — sin esto, un documento reclasificado a otro dominio (o un
        dominio eliminado entre dos reconstrucciones) dejaba su copia física
        huérfana en disco para siempre (AUDIT_CODE, sesión 2026-09-08).

        Returns:
            La carpeta de salida (`<project.root_path>/<context.output_folder_name>/`).

        Raises:
            IncompleteConversionArtifactsError: Si a algún documento le falta el
                original, el `.md` o el `.json` en disco — antes de tocar nada.
        """
        output_root = Path(project.root_path) / context.output_folder_name

        for domain in context.domains:
            for document in domain.documents:
                self._validate_artifacts(document)

        current_slugs = {domain.slug for domain in context.domains}
        await self._remove_stale_domain_dirs(output_root, current_slugs)

        for domain in context.domains:
            await self._reset_domain_dir(output_root, domain.slug)
            for document in domain.documents:
                await self._copy_document(output_root, domain.slug, document)
        return output_root

    @staticmethod
    def _validate_artifacts(document: DomainDocument) -> None:
        for artifact in (Path(document.source_path), Path(document.markdown_path), Path(document.json_path)):
            if not artifact.is_file():
                raise IncompleteConversionArtifactsError(f"Falta '{artifact}' — no se puede reorganizar '{document.source_path}' a medias.")

    async def _remove_stale_domain_dirs(self, output_root: Path, current_slugs: set[str]) -> None:
        if not output_root.is_dir():
            return
        stale_dirs = await asyncio.to_thread(self._list_stale_domain_dirs, output_root, current_slugs)
        for stale_dir in stale_dirs:
            await asyncio.to_thread(shutil.rmtree, stale_dir)
            self.logger.info(f"Copia obsoleta eliminada tras reorganizar: {stale_dir}")

    @staticmethod
    def _list_stale_domain_dirs(output_root: Path, current_slugs: set[str]) -> list[Path]:
        return [entry for entry in output_root.iterdir() if entry.is_dir() and entry.name not in current_slugs]

    async def _reset_domain_dir(self, output_root: Path, domain_slug: str) -> None:
        """Borra `output_root/<domain_slug>/` si ya existía de una reconstrucción
        anterior, para que documentos que ya no pertenecen a este dominio (o que
        se eliminaron) no queden como sub-carpetas huérfanas."""
        domain_dir = output_root / domain_slug
        if domain_dir.is_dir():
            await asyncio.to_thread(shutil.rmtree, domain_dir)

    async def _copy_document(self, output_root: Path, domain_slug: str, document: DomainDocument) -> None:
        source = Path(document.source_path)
        markdown = Path(document.markdown_path)
        json_file = Path(document.json_path)
        document_type, stem = resolve_document_slug_parts(document)

        target_dir = output_root / domain_slug / document_type / stem
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, source, target_dir / source.name)
        await asyncio.to_thread(shutil.copy2, markdown, target_dir / markdown.name)
        await asyncio.to_thread(shutil.copy2, json_file, target_dir / json_file.name)


__all__ = ["Reorganizer", "resolve_document_slug_parts"]
