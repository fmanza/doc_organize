"""
Manifiesto de taxonomía documental por proyecto: una lista de ejes (2.0.0), con dominio y tipo de material como ejes
organizadores.
"""

import asyncio

from pathlib import Path

from doc_organize.context.taxonomy_front_matter import manifest_from_text, render_front_matter
from doc_organize.core.constants import TAXONOMY_MANIFEST_FILE_NAME
from doc_organize.core.exceptions import TaxonomyManifestError
from doc_organize.core.models import Project, TaxonomyManifest
from doc_organize.utils.atomic_write import write_text_atomic
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

MANIFEST_FILE_NAME = TAXONOMY_MANIFEST_FILE_NAME


async def load_taxonomy_manifest(project: Project) -> TaxonomyManifest | None:
    """Carga el manifiesto de taxonomía de `project`, si existe.

    Lee `<project.root_path>/taxonomy_manifest.md`: el front matter YAML (delimitado por
    las dos primeras líneas `---`) se valida como `TaxonomyManifest`; el resto del fichero
    es prosa libre para lectura humana (descripción, tablas, diagramas Mermaid) y no se
    parsea — mismo patrón de front matter + cuerpo libre que `standards.md` de
    `doc_calidad` (ver `.ai/sessions/.../00_REQUEST.md` de esta sesión).

    Args:
        project: Proyecto cuyo `root_path` se inspecciona.

    Returns:
        El `TaxonomyManifest` ya validado, o `None` si el proyecto no tiene
        `taxonomy_manifest.md` — modo sin manifiesto, comportamiento de `ContextBuilder`
        sin cambios respecto al eje único de dominio.

    Raises:
        TaxonomyManifestError: El fichero existe pero no empieza con el delimitador de
            front matter, no lo cierra, el YAML no es válido, o no cumple el schema de
            `TaxonomyManifest` (p. ej. catálogo de dominios o de tipos de material vacío).

    Example:
        >>> import asyncio, tempfile
        >>> from datetime import UTC, datetime
        >>> from doc_organize.core.models import Project
        >>> async def main():
        ...     root = tempfile.mkdtemp()
        ...     project = Project(name="Demo", root_path=root, created_at=datetime.now(UTC).isoformat())
        ...     return await load_taxonomy_manifest(project)
        >>> asyncio.run(main())  # doctest: +SKIP
        None
    """
    manifest_path = Path(project.root_path) / MANIFEST_FILE_NAME
    if not await asyncio.to_thread(manifest_path.is_file):
        return None

    raw = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
    manifest = manifest_from_text(raw, str(manifest_path), TaxonomyManifestError)
    logger.info(f"Manifiesto de taxonomía cargado de '{manifest_path}': {_describe_axes(manifest)}")
    return manifest


async def save_taxonomy_manifest(project: Project, raw_markdown: str) -> TaxonomyManifest:
    """Guarda `raw_markdown` como `<project.root_path>/taxonomy_manifest.md`, tras validarlo.

    Pensado para persistir el
    borrador que el usuario revisó/editó (`draft_taxonomy_manifest` genera el texto vía
    `render_taxonomy_manifest_markdown`, pero nunca lo escribía a disco -- ver el docstring de
    esa función). Valida ANTES de escribir, con la misma lectura que usa `load_taxonomy_manifest()`
    (formato 2.0 o 1.x migrado en memoria), para no dejar nunca en disco un fichero que la propia
    app no podría releer. Guarda el texto tal cual: un manifiesto de 1.x sigue siendo 1.x en disco
    hasta que el consumidor lo migre (`migrate_manifest_v1`).

    Escritura atómica (`utils.atomic_write.write_text_atomic`, L-8e): una construcción de contexto concurrente que esté leyendo el fichero
    (`_load_taxonomy_manifest_or_400`) nunca ve un `taxonomy_manifest.md` a medio escribir.

    Args:
        project: Proyecto cuyo `root_path` recibe el fichero.
        raw_markdown: Contenido completo del fichero (front matter YAML + prosa), tal
            cual lo edita el usuario -- normalmente partiendo del texto que devolvió
            `draft_taxonomy_manifest`.

    Returns:
        El `TaxonomyManifest` ya validado (para que el llamador pueda responder sin
        releer el fichero).

    Raises:
        TaxonomyManifestError: `raw_markdown` no empieza con el delimitador de front
            matter, no lo cierra, el YAML no es válido, o no cumple el schema de
            `TaxonomyManifest`.
    """
    manifest_path = Path(project.root_path) / MANIFEST_FILE_NAME
    manifest = manifest_from_text(raw_markdown, str(manifest_path), TaxonomyManifestError)

    # L-8e (G31): temporal con nombre aleatorio y creado en exclusiva, nunca `taxonomy_manifest.tmp` de nombre fijo.
    await asyncio.to_thread(write_text_atomic, manifest_path, raw_markdown)
    logger.info(f"Manifiesto de taxonomía guardado en '{manifest_path}': {_describe_axes(manifest)}")
    return manifest


def _describe_axes(manifest: TaxonomyManifest) -> str:
    return ", ".join(f"{axis.key} ({len(axis.entries)})" for axis in manifest.axes)


def render_taxonomy_manifest_markdown(
    manifest: TaxonomyManifest, *, reasoning: str | None, sample_document_count: int, total_document_count: int
) -> str:
    """Renderiza `manifest` en el mismo formato de fichero que `load_taxonomy_manifest()` espera
    (front matter YAML delimitado por `---` + prosa libre) — listo para que el usuario lo revise,
    edite y guarde a mano como `<project.root_path>/taxonomy_manifest.md` (o como una plantilla
    nueva de `TaxonomyTemplateRegistry`).

    Pensado para componer la respuesta de un
    borrador propuesto por IA (`ai.draft_taxonomy`) — nunca escribe nada en disco por
    sí mismo; no existe hoy ningún endpoint que persista `taxonomy_manifest.md` por el usuario, así
    que "confirmar" el borrador es siempre una acción manual fuera de esta función.

    Args:
        manifest: Catálogo propuesto (`TaxonomyManifestDraftResult.to_manifest()`). `title`/`description` del
            propio `manifest` se ignoran — solo relevantes para una plantilla compartida (ver `TaxonomyManifest`), no
            para un manifiesto de proyecto.
        reasoning: Justificación devuelta por la IA (`TaxonomyManifestDraftResult.reasoning`), o
            `None` si no la reportó.
        sample_document_count: Documentos realmente enviados a la IA.
        total_document_count: Total de documentos convertidos del proyecto en el momento de pedir
            el borrador.

    Returns:
        Texto completo del fichero (formato 2.0), empezando por el front matter YAML.

    Example:
        >>> from doc_organize.core.models import TaxonomyEntry, TaxonomyManifestDraftResult
        >>> manifest = TaxonomyManifestDraftResult(
        ...     domains=[TaxonomyEntry(slug="calidad", name="Calidad")],
        ...     material_types=[TaxonomyEntry(slug="procedimiento", name="Procedimiento")],
        ... ).to_manifest()
        >>> text = render_taxonomy_manifest_markdown(manifest, reasoning=None, sample_document_count=5, total_document_count=20)
        >>> text.startswith("---\\nschema: 2\\naxes:")
        True
    """
    front_matter = render_front_matter(manifest.model_copy(update={"title": None, "description": None}))
    rows = "".join(f"| {axis.name} | {', '.join(entry.name for entry in axis.entries)} |\n" for axis in manifest.axes)
    reasoning_paragraph = f"\n{reasoning}\n" if reasoning else ""
    return (
        f"{front_matter}\n"
        "# Borrador de taxonomía (generado por IA)\n\n"
        f"> Borrador generado automáticamente a partir de una muestra de {sample_document_count} de "
        f"{total_document_count} documentos convertidos. Revísalo y edítalo antes de guardarlo como "
        "`taxonomy_manifest.md` — no se aplica ningún cambio automáticamente.\n"
        f"{reasoning_paragraph}\n"
        "| Eje | Propuestas |\n"
        "|---|---|\n"
        f"{rows}"
    )


__all__ = ["MANIFEST_FILE_NAME", "load_taxonomy_manifest", "render_taxonomy_manifest_markdown", "save_taxonomy_manifest"]
