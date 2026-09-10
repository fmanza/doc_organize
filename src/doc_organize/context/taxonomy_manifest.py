"""
Manifiesto de taxonomía documental por proyecto: dominios + tipos de material de origen.
"""

import asyncio

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


__all__ = ["MANIFEST_FILE_NAME", "load_taxonomy_manifest"]
