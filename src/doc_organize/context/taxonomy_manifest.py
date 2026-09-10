"""
Manifiesto de taxonomía documental por proyecto: dominios + tipos de material de origen.
"""

import asyncio
import os

from pathlib import Path

import yaml

from pydantic import ValidationError

from doc_organize.core.exceptions import TaxonomyManifestError
from doc_organize.core.models import Project, TaxonomyManifest
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

MANIFEST_FILE_NAME = "taxonomy_manifest.md"
_FRONT_MATTER_DELIMITER = "---"


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
    front_matter = _extract_front_matter(raw, manifest_path)
    manifest = _parse_front_matter(front_matter, manifest_path)
    logger.info(
        f"Manifiesto de taxonomía cargado de '{manifest_path}': {len(manifest.domains)} dominio(s), {len(manifest.material_types)} tipo(s) de material"
    )
    return manifest


async def save_taxonomy_manifest(project: Project, raw_markdown: str) -> TaxonomyManifest:
    """Guarda `raw_markdown` como `<project.root_path>/taxonomy_manifest.md`, tras validarlo.

    Usado por `web/routes/context.py::save_taxonomy_manifest_endpoint` para persistir el
    borrador que el usuario revisó/editó (`draft_taxonomy_manifest` genera el texto vía
    `render_taxonomy_manifest_markdown`, pero nunca lo escribía a disco -- ver el docstring de
    esa función). Valida ANTES de escribir, con los mismos `_extract_front_matter`/
    `_parse_front_matter` que usa `load_taxonomy_manifest()`, para no dejar nunca en disco un
    fichero que la propia app no podría releer.

    Escritura atómica (fichero temporal + `os.replace`, mismo patrón que
    `ContextRegistry._write_text_atomic`, duplicado aquí -- política "prohibido
    refactorizar"): una construcción de contexto concurrente que esté leyendo el fichero
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
    front_matter = _extract_front_matter(raw_markdown, manifest_path)
    manifest = _parse_front_matter(front_matter, manifest_path)

    tmp_path = manifest_path.with_suffix(".tmp")
    await asyncio.to_thread(tmp_path.write_text, raw_markdown, encoding="utf-8")
    await asyncio.to_thread(os.replace, tmp_path, manifest_path)
    logger.info(
        f"Manifiesto de taxonomía guardado en '{manifest_path}': {len(manifest.domains)} dominio(s), {len(manifest.material_types)} tipo(s) de material"
    )
    return manifest


def _extract_front_matter(raw: str, manifest_path: Path) -> str:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise TaxonomyManifestError(f"'{manifest_path}' debe empezar con el delimitador de front matter YAML ('---').")
    try:
        closing_index = lines.index(_FRONT_MATTER_DELIMITER, 1)
    except ValueError as exc:
        raise TaxonomyManifestError(f"'{manifest_path}' no cierra el front matter YAML (falta un segundo '---').") from exc
    return "\n".join(lines[1:closing_index])


def _parse_front_matter(front_matter: str, manifest_path: Path) -> TaxonomyManifest:
    try:
        payload = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise TaxonomyManifestError(f"El front matter YAML de '{manifest_path}' no es válido: {exc}") from exc
    if not isinstance(payload, dict):
        raise TaxonomyManifestError(f"El front matter de '{manifest_path}' debe ser un mapeo YAML con 'domains'/'material_types'.")
    try:
        return TaxonomyManifest.model_validate(payload)
    except ValidationError as exc:
        raise TaxonomyManifestError(f"El front matter de '{manifest_path}' no cumple el schema de taxonomía: {exc}") from exc


def render_taxonomy_manifest_markdown(
    manifest: TaxonomyManifest, *, reasoning: str | None, sample_document_count: int, total_document_count: int
) -> str:
    """Renderiza `manifest` en el mismo formato de fichero que `load_taxonomy_manifest()` espera
    (front matter YAML delimitado por `---` + prosa libre) — listo para que el usuario lo revise,
    edite y guarde a mano como `<project.root_path>/taxonomy_manifest.md` (o como una plantilla
    nueva de `TaxonomyTemplateRegistry`).

    Usado por `web/routes/context.py::draft_taxonomy_manifest` para componer la respuesta de un
    borrador propuesto por IA (`ai.TaxonomyManifestDraftClient`) — nunca escribe nada en disco por
    sí mismo; no existe hoy ningún endpoint que persista `taxonomy_manifest.md` por el usuario, así
    que "confirmar" el borrador es siempre una acción manual fuera de esta función.

    Args:
        manifest: Catálogo propuesto (`domains`/`material_types`). `title`/`description` del
            propio `manifest` se ignoran — solo relevantes para una plantilla compartida (ver
            `TaxonomyManifest`), no para un manifiesto de proyecto.
        reasoning: Justificación devuelta por la IA (`TaxonomyManifestDraftResult.reasoning`), o
            `None` si no la reportó.
        sample_document_count: Documentos realmente enviados a la IA.
        total_document_count: Total de documentos convertidos del proyecto en el momento de pedir
            el borrador.

    Returns:
        Texto completo del fichero, empezando por el front matter YAML.

    Example:
        >>> from doc_organize.core.models import TaxonomyCatalogEntry
        >>> manifest = TaxonomyManifest(
        ...     domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad")],
        ...     material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento")],
        ... )
        >>> text = render_taxonomy_manifest_markdown(manifest, reasoning=None, sample_document_count=5, total_document_count=20)
        >>> text.startswith("---\\ndomains:")
        True
    """
    front_matter = yaml.safe_dump(
        {
            "domains": [entry.model_dump(exclude_none=True) for entry in manifest.domains],
            "material_types": [entry.model_dump(exclude_none=True) for entry in manifest.material_types],
        },
        allow_unicode=True,
        sort_keys=False,
    )
    domain_names = ", ".join(entry.name for entry in manifest.domains)
    material_type_names = ", ".join(entry.name for entry in manifest.material_types)
    reasoning_paragraph = f"\n{reasoning}\n" if reasoning else ""
    return (
        f"---\n{front_matter}---\n\n"
        "# Borrador de taxonomía (generado por IA)\n\n"
        f"> Borrador generado automáticamente a partir de una muestra de {sample_document_count} de "
        f"{total_document_count} documentos convertidos. Revísalo y edítalo antes de guardarlo como "
        "`taxonomy_manifest.md` — no se aplica ningún cambio automáticamente.\n"
        f"{reasoning_paragraph}\n"
        "| Eje | Propuestas |\n"
        "|---|---|\n"
        f"| Dominio | {domain_names} |\n"
        f"| Tipo de material | {material_type_names} |\n"
    )


__all__ = ["MANIFEST_FILE_NAME", "load_taxonomy_manifest", "render_taxonomy_manifest_markdown", "save_taxonomy_manifest"]
