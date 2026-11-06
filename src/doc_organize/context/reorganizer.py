"""
Copia física de los documentos clasificados a la carpeta reorganizada del proyecto.
"""

import asyncio
import hashlib
import os
import unicodedata

from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath

from doc_organize.core.exceptions import IncompleteConversionArtifactsError, InvalidPathError
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.projects.layout import validate_output_folder_name
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import copy_file_nofollow, copy_tree_nofollow, ensure_no_symlinks, ensure_tree_has_no_symlinks, remove_tree

logger = get_logger(__name__)


def resolve_document_slug_parts(document: DomainDocument) -> tuple[str, str]:
    """`(tipo, stem)`: determina la carpeta de un documento clasificado
    bajo `<output_folder_name>/<dominio>/<tipo>/<stem>/`.

    Compartida entre `Reorganizer` (ruta real en disco) y `SiteGenerator` (ruta
    del `.md` en el `nav` de `zensical.toml`, siempre con `/` literales — nunca
    `Path`, que en Windows usaría `\\`) — antes cada uno repetía
    `Path(document.markdown_path).stem` por su cuenta, sin nada que garantizara
    que no divergieran (AUDIT_CODE, sesión 2026-09-09).

    `tipo` es `document.material_type` (tipo de material de origen del manifiesto de
    taxonomía) cuando está definido, o `document.document_type` (extensión) en el modo
    sin manifiesto — mismo campo `tipo` de siempre, solo cambia qué lo resuelve, así que
    el modo sin manifiesto (`material_type=None`) queda con el comportamiento idéntico
    al de antes de esta sesión.
    """
    stem = Path(document.markdown_path).stem
    tipo = document.material_type if document.material_type is not None else document.document_type
    return tipo, stem


_SUFFIX_LENGTHS = (8, 16, 64)
"""Hex del SHA-256 del sufijo de colisión (L-8d): 8 basta; los otros solo si aun así chocan."""


def _collision_key(name: str) -> str:
    """Igual criterio que una carpeta en SMB/Windows: NFC, sin mayúsculas y sin puntos ni espacios finales."""
    return unicodedata.normalize("NFC", name.rstrip(" .")).casefold()


def _relative_markdown_path(document: DomainDocument, project_root: str | Path) -> str:
    """`.md` relativo a la raíz del proyecto (POSIX): replica la ruta de origen relativa y no depende del montaje."""
    markdown = Path(os.path.abspath(document.markdown_path))
    try:
        return markdown.relative_to(os.path.abspath(project_root)).as_posix()
    except ValueError:
        return markdown.as_posix()


def resolve_organized_paths(domain: Domain, project_root: str | Path) -> list[str]:
    """Ruta POSIX del `.md` copiado de cada documento de `domain`, relativa a la carpeta reorganizada (L-8d, G30).

    Una por documento, en el mismo orden que `domain.documents`: `<dominio>/<tipo>/<carpeta>/<stem>.md`. Sin
    colisiones, `<carpeta>` es el `stem` del `.md`, igual que en 0.13.0. Si dos o más documentos del dominio comparten
    `(tipo, stem)` sin distinguir mayúsculas (en SMB/Windows «Acta» y «acta» son la misma carpeta), **todos** ellos
    llevan `<stem>-<8 hex>`, del SHA-256 de su `.md` relativo a `project_root`: determinista y sin depender del orden.
    `img/<stem>/` y los nombres de fichero no cambian (el `.md` sigue resolviendo sus imágenes).

    Única fuente de la ruta para `Reorganizer` (disco) y `SiteGenerator` (`nav`), que la recalculan siempre: nunca se
    usa `DomainDocument.organized_path` leído de disco.

    Example:
        >>> from doc_organize.core.models import Domain, DomainDocument
        >>> def doc(name):
        ...     return DomainDocument(source_path=name, markdown_path=f"/p/Conversión/{name}.md", json_path="x.json",
        ...                           title="t", document_type="pdf", confidence=1.0)
        >>> domain = Domain(slug="calidad", name="Calidad", documents=[doc("a/Acta"), doc("b/acta"), doc("c/Informe")])
        >>> [len(path.split("/")[2]) for path in resolve_organized_paths(domain, "/p")]
        [13, 13, 7]
    """
    parts = [resolve_document_slug_parts(document) for document in domain.documents]
    groups: dict[tuple[str, str], list[int]] = {}
    for index, (tipo, stem) in enumerate(parts):
        groups.setdefault((_collision_key(tipo), _collision_key(stem)), []).append(index)

    folders = [stem for _tipo, stem in parts]
    plain_keys = {key for key, members in groups.items() if len(members) == 1}
    for key, members in groups.items():
        if len(members) == 1:
            continue
        digests = [hashlib.sha256(_relative_markdown_path(domain.documents[i], project_root).encode("utf-8")).hexdigest() for i in members]
        for length in _SUFFIX_LENGTHS:
            candidates = [f"{parts[i][1]}-{digest[:length]}" for i, digest in zip(members, digests, strict=True)]
            candidate_keys = [(key[0], _collision_key(name)) for name in candidates]
            if len(set(candidate_keys)) == len(candidates) and not plain_keys.intersection(candidate_keys):
                break
        for i, name in zip(members, candidates, strict=True):
            folders[i] = name

    return [PurePosixPath(domain.slug, tipo, folder, f"{stem}.md").as_posix() for (tipo, stem), folder in zip(parts, folders, strict=True)]


def assign_organized_paths(context: Context, project_root: str | Path) -> None:
    """Rellena `DomainDocument.organized_path` de todos los documentos de `context` (ver `resolve_organized_paths`)."""
    for domain in context.domains:
        for document, organized_path in zip(domain.documents, resolve_organized_paths(domain, project_root), strict=True):
            document.organized_path = organized_path


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

    No sigue enlaces simbólicos (L-8a, G27; mismo criterio que la deduplicación desde
    0.12.1): la carpeta de salida no puede ser ni pasar por un enlace
    (`InvalidPathError` antes de tocar nada), y un documento con algún tramo enlazado
    (original, `.md`, `.json`, `img/<stem>/` o lo que contiene) falla solo, sin copiar
    el destino del enlace: queda en `Context.reorganize_failed_documents` y en
    `on_document_failed`, y el resto sigue.

    Dos documentos del mismo dominio/tipo con el mismo `stem` (sin distinguir
    mayúsculas) ya no comparten carpeta: cada uno va a `<stem>-<8 hex>/` (L-8d, G30;
    ver `resolve_organized_paths`). Hasta 0.13.0 el segundo sobrescribía al primero.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from datetime import UTC, datetime
        >>> async def main():
        ...     root = tempfile.mkdtemp()
        ...     project = Project(name="Demo", root_path=root, created_at=datetime.now(UTC).isoformat())
        ...     context = Context(project_name="Demo", created_at="2026-01-01", updated_at="2026-01-01")
        ...     output_root = await Reorganizer().reorganize(project, context)
        ...     return output_root.name, context.reorganize_failed_documents
        >>> asyncio.run(main())  # doctest: +SKIP
        ('organizado', [])
    """

    def __init__(self) -> None:
        self.logger = logger

    async def reorganize(
        self,
        project: Project,
        context: Context,
        on_document_copied: Callable[[int, int, str], Awaitable[None]] | None = None,
        *,
        on_document_failed: Callable[[int, int, str, str], Awaitable[None]] | None = None,
    ) -> Path:
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
        huérfana en disco para siempre (AUDIT_CODE, sesión 2026-09-08). Un enlace
        que aparezca en el lugar de una de esas carpetas se quita (el enlace, nunca
        su destino).

        Un documento que no se puede copiar (`OSError`: un tramo enlazado, un permiso
        denegado...) no interrumpe el resto (L-8a, G27): se borra lo que se hubiera
        copiado de él, se añade su `source_path` a `context.reorganize_failed_documents`
        (que se rehace en cada llamada) y se notifica por `on_document_failed`.

        Args:
            on_document_copied: Si se da, se invoca `await on_document_copied(index, total, source_path)`
                tras copiar cada documento (`index` empezando en 1) — pensado para
                que el consumidor retransmita el progreso en tiempo real (semáforo). `None` (default) no tiene efecto
                ninguno: los llamadores existentes no cambian de comportamiento.
            on_document_failed: Si se da, se invoca `await on_document_failed(index, total, source_path, error)`
                por cada documento que no se pudo copiar (mismo `index` que habría tenido en
                `on_document_copied`).

        Returns:
            La carpeta de salida (`<project.root_path>/<context.output_folder_name>/`).

        Rellena `DomainDocument.organized_path` de cada documento con la ruta en la que
        queda su `.md` (L-8d), también la de los que fallan (es donde habría quedado).

        Raises:
            InvalidPathError: Si `context.output_folder_name` no es válido (L-8f) o la carpeta de salida es o pasa
                por un enlace — antes de tocar nada.
            IncompleteConversionArtifactsError: Si a algún documento le falta el
                original, el `.md` o el `.json` en disco — antes de tocar nada.
        """
        output_root = Path(project.root_path) / validate_output_folder_name(context.output_folder_name)
        await asyncio.to_thread(self.check_output_root, output_root)

        for domain in context.domains:
            for document in domain.documents:
                self._validate_artifacts(document)

        current_slugs = {domain.slug for domain in context.domains}
        await self._remove_stale_domain_dirs(output_root, current_slugs)

        total = sum(len(domain.documents) for domain in context.domains)
        index = 0
        failed: list[str] = []
        for domain in context.domains:
            await self._reset_domain_dir(output_root, domain.slug)
            organized_paths = resolve_organized_paths(domain, project.root_path)
            for document, organized_path in zip(domain.documents, organized_paths, strict=True):
                index += 1
                document.organized_path = organized_path
                try:
                    await self._copy_document(output_root, organized_path, document)
                except OSError as exc:
                    failed.append(document.source_path)
                    self.logger.warning(f"No se pudo reorganizar '{document.source_path}': {exc}")
                    if on_document_failed is not None:
                        await on_document_failed(index, total, document.source_path, str(exc))
                    continue
                if on_document_copied is not None:
                    await on_document_copied(index, total, document.source_path)
        context.reorganize_failed_documents = failed
        return output_root

    @staticmethod
    def check_output_root(output_root: Path) -> None:
        """Comprueba que la carpeta de salida no sea ni pase por un enlace simbólico (L-8a).

        Raises:
            InvalidPathError: Si algún tramo existente de `output_root` es un enlace.
        """
        try:
            ensure_no_symlinks(output_root)
        except OSError as exc:
            raise InvalidPathError(f"La carpeta reorganizada '{output_root}' no puede ser ni pasar por un enlace simbólico.") from exc

    @staticmethod
    def _validate_artifacts(document: DomainDocument) -> None:
        for artifact in (Path(document.source_path), Path(document.markdown_path), Path(document.json_path)):
            # Un enlace no es un artefacto que falte: falla solo ese documento al copiarlo (L-8a).
            if not artifact.is_file() and not artifact.is_symlink():
                raise IncompleteConversionArtifactsError(f"Falta '{artifact}' — no se puede reorganizar '{document.source_path}' a medias.")

    async def _remove_stale_domain_dirs(self, output_root: Path, current_slugs: set[str]) -> None:
        if not output_root.is_dir():
            return
        stale_dirs = await asyncio.to_thread(self._list_stale_domain_dirs, output_root, current_slugs)
        for stale_dir in stale_dirs:
            await asyncio.to_thread(_remove_dir_or_link, stale_dir)
            self.logger.info(f"Copia obsoleta eliminada tras reorganizar: {stale_dir}")

    @staticmethod
    def _list_stale_domain_dirs(output_root: Path, current_slugs: set[str]) -> list[Path]:
        return [entry for entry in output_root.iterdir() if entry.is_dir() and entry.name not in current_slugs]

    async def _reset_domain_dir(self, output_root: Path, domain_slug: str) -> None:
        """Borra `output_root/<domain_slug>/` si ya existía de una reconstrucción
        anterior, para que documentos que ya no pertenecen a este dominio (o que
        se eliminaron) no queden como sub-carpetas huérfanas."""
        domain_dir = output_root / domain_slug
        if domain_dir.is_dir() or domain_dir.is_symlink():
            await asyncio.to_thread(_remove_dir_or_link, domain_dir)

    async def delete_output(self, project: Project, context: Context) -> None:
        """Borra `<project.root_path>/<context.output_folder_name>/` por completo, si existe.

        Usado al eliminar el contexto de un proyecto
        para volver al estado anterior a la primera construcción — sin esto, la
        copia física quedaría huérfana en disco tras borrar `context.json`. Si la
        carpeta es un enlace, se quita el enlace (nunca su destino).

        Raises:
            InvalidPathError: Si `context.output_folder_name` no es válido (L-8f) o la raíz del proyecto pasa por un
                enlace simbólico.
        """
        output_root = Path(project.root_path) / validate_output_folder_name(context.output_folder_name)
        await asyncio.to_thread(self.check_output_root, output_root.parent)
        if await asyncio.to_thread(output_root.is_symlink) or await asyncio.to_thread(output_root.is_dir):
            await asyncio.to_thread(_remove_dir_or_link, output_root)

    async def _copy_document(self, output_root: Path, organized_path: str, document: DomainDocument) -> None:
        await asyncio.to_thread(self._copy_document_sync, output_root, organized_path, document)

    @staticmethod
    def _copy_document_sync(output_root: Path, organized_path: str, document: DomainDocument) -> None:
        """Copia los artefactos de `document` a la carpeta de `organized_path` sin seguir enlaces; si falla, borra lo copiado."""
        source = Path(document.source_path)
        markdown = Path(document.markdown_path)
        json_file = Path(document.json_path)
        _document_type, stem = resolve_document_slug_parts(document)

        # Todo se comprueba antes de copiar nada: un enlace en cualquier artefacto no deja ni una copia parcial.
        for artifact in (source, markdown, json_file):
            ensure_no_symlinks(artifact)
        images_dir: Path | None = None
        if document.images_dir is not None:
            images_dir = ensure_no_symlinks(document.images_dir)
            if os.path.isdir(images_dir):
                ensure_tree_has_no_symlinks(images_dir)
            else:
                images_dir = None

        target_dir = ensure_no_symlinks(output_root.joinpath(*PurePosixPath(organized_path).parent.parts))
        created = not os.path.lexists(target_dir)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # Con `overwrite`: la carpeta es solo de este documento (L-8d); solo pisa restos de una copia anterior.
            copy_file_nofollow(source, target_dir / source.name, overwrite=True)
            copy_file_nofollow(markdown, target_dir / markdown.name, overwrite=True)
            copy_file_nofollow(json_file, target_dir / json_file.name, overwrite=True)
            if images_dir is not None:
                # Mismo layout relativo ("img/<stem>/") que asume la referencia
                # `![](img/<stem>/imagen.png)` del `.md` (ver `converter.resolve_images_dir`)
                # — el `.md` no se reescribe, así que la carpeta debe quedar sibling
                # con el mismo nombre para que la ruta relativa siga resolviendo.
                copy_tree_nofollow(images_dir, target_dir / "img" / stem)
        except OSError:
            if created:
                remove_tree(target_dir, ignore_errors=True)
            raise


def _remove_dir_or_link(path: Path) -> None:
    """Borra la carpeta `path` entera o, si es un enlace (o una unión de Windows), solo el enlace; si no existe, nada."""
    if path.is_symlink() or path.is_junction():
        os.unlink(path)
    elif path.is_dir():
        remove_tree(path)


__all__ = ["Reorganizer", "assign_organized_paths", "resolve_document_slug_parts", "resolve_organized_paths"]
