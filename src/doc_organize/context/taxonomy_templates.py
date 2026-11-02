"""
Plantillas de manifiesto de taxonomía como texto (L-8c, hueco G29 de doc_organize_web).

Parsear y renderizar el formato de fichero de una plantilla (front matter YAML + prosa libre) y leer las plantillas
empaquetadas con doc_organize, sin carpeta de usuario ni ``Path.home()``: un consumidor que guarda las plantillas en
su propia base de datos usa estas funciones; ``TaxonomyTemplateRegistry`` las usa por dentro.
"""

import re

from pathlib import Path

import yaml

from pydantic import ValidationError

from doc_organize.core.exceptions import TaxonomyTemplateError
from doc_organize.core.models import TaxonomyManifest, TaxonomyTemplateSummary
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

TEMPLATE_FILE_EXTENSION = ".md"
_FRONT_MATTER_DELIMITER = "---"

#: Plantillas de ejemplo distribuidas con el propio paquete (ver `MANIFEST.in`) — de solo lectura, nunca escritas por
#: la aplicación.
_BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "taxonomy_templates_builtin"

#: Un nombre de plantilla llega desde un payload de API y se usa para construir una
#: ruta de fichero (`<templates_dir>/<name>.md`) — se valida contra este patrón ANTES
#: de tocar el filesystem, para que `../otra-cosa` o rutas absolutas nunca lleguen a
#: `Path.__truediv__` (path traversal fuera de las carpetas de plantillas).
_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def parse_taxonomy_template(text: str, *, source: str = "<texto>") -> TaxonomyManifest:
    """Valida el front matter YAML de `text` (formato de fichero de una plantilla) como `TaxonomyManifest`.

    El cuerpo tras el front matter es prosa libre y no se parsea.

    Args:
        text: Contenido completo de la plantilla.
        source: Cómo se nombra la plantilla en los mensajes de error (`TaxonomyTemplateRegistry` pasa la ruta).

    Raises:
        TaxonomyTemplateError: Falta el delimitador de front matter o no se cierra, el YAML no es válido o no cumple
            el schema de `TaxonomyManifest` — los mismos errores que al cargar una plantilla de fichero.

    Example:
        >>> manifest = parse_taxonomy_template(
        ...     "---\\ndomains:\\n  - slug: calidad\\n    name: Calidad\\n"
        ...     "material_types:\\n  - slug: procedimiento\\n    name: Procedimiento\\n---\\n# Notas\\n"
        ... )
        >>> manifest.domains[0].slug
        'calidad'
    """
    front_matter = _extract_front_matter(text, source)
    return _parse_front_matter(front_matter, source)


def render_taxonomy_template(manifest: TaxonomyManifest, body: str = "") -> str:
    """Escribe `manifest` en el formato de fichero de una plantilla: front matter YAML entre `---` y, detrás, `body`.

    Ida y vuelta estable: `parse_taxonomy_template(render_taxonomy_template(m)) == m` para cualquier `TaxonomyManifest`
    (incluidos `title`/`description` vacíos y textos con saltos de línea o `---`).

    Args:
        manifest: Catálogo a escribir.
        body: Prosa libre (Markdown) tras el front matter; vacío por defecto.

    Example:
        >>> from doc_organize.core.models import TaxonomyCatalogEntry
        >>> manifest = TaxonomyManifest(
        ...     title="Calidad",
        ...     domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad")],
        ...     material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento")],
        ... )
        >>> text = render_taxonomy_template(manifest, "# Notas\\n")
        >>> text.splitlines()[:2]
        ['---', 'title: Calidad']
        >>> parse_taxonomy_template(text) == manifest
        True
    """
    payload: dict[str, object] = {}
    if manifest.title is not None:
        payload["title"] = manifest.title
    if manifest.description is not None:
        payload["description"] = manifest.description
    payload["domains"] = [entry.model_dump(exclude_none=True) for entry in manifest.domains]
    payload["material_types"] = [entry.model_dump(exclude_none=True) for entry in manifest.material_types]
    # `width` infinito: sin plegar líneas largas. Los saltos de línea dentro de un valor salen escapados (`\n`) en una
    # cadena entre comillas dobles (`_TemplateDumper`), así que ninguna línea del front matter puede ser un `---` que
    # lo cierre antes ni partirse distinto al releerla con `splitlines()`.
    front_matter = yaml.dump(payload, Dumper=_TemplateDumper, allow_unicode=True, sort_keys=False, width=float("inf"))
    text = f"{_FRONT_MATTER_DELIMITER}\n{front_matter}{_FRONT_MATTER_DELIMITER}\n"
    return f"{text}\n{body}" if body else text


def list_builtin_templates() -> list[TaxonomyTemplateSummary]:
    """Plantillas empaquetadas con doc_organize, ordenadas por nombre (una con front matter inválido se omite).

    Example:
        >>> "calidad" in [summary.name for summary in list_builtin_templates()]
        True
    """
    summaries = []
    for name in list_template_names(_BUILTIN_TEMPLATES_DIR):
        try:
            manifest = load_builtin_template(name)
        except TaxonomyTemplateError as exc:
            logger.warning(f"Plantilla de taxonomía empaquetada '{name}' omitida: {exc}")
            continue
        summaries.append(TaxonomyTemplateSummary(name=name, title=manifest.title, description=manifest.description))
    return summaries


def load_builtin_template(name: str) -> TaxonomyManifest:
    """Carga la plantilla empaquetada `name`.

    Raises:
        TaxonomyTemplateError: `name` no es un slug válido, no existe esa plantilla o su front matter no es válido.

    Example:
        >>> load_builtin_template("calidad").domains[0].slug
        'calidad'
    """
    template_path = template_file(_BUILTIN_TEMPLATES_DIR, name)
    if not template_path.is_file():
        raise TaxonomyTemplateError(f"No existe ninguna plantilla de taxonomía llamada '{name}' en '{_BUILTIN_TEMPLATES_DIR}'.")
    return parse_taxonomy_template(template_path.read_text(encoding="utf-8"), source=str(template_path))


def template_file(directory: Path, name: str) -> Path:
    """`<directory>/<name>.md`, tras validar que `name` sea un slug (minúsculas, dígitos y guiones).

    Raises:
        TaxonomyTemplateError: `name` no es un nombre de plantilla válido.
    """
    if not _TEMPLATE_NAME_PATTERN.match(name):
        raise TaxonomyTemplateError(f"'{name}' no es un nombre de plantilla válido — solo minúsculas, dígitos y guiones (p. ej. 'sgi-iso27001').")
    return directory / f"{name}{TEMPLATE_FILE_EXTENSION}"


def list_template_names(directory: Path) -> list[str]:
    """Nombres (sin extensión) de las plantillas de `directory`, ordenados; omite los que no son un slug válido."""
    if not directory.is_dir():
        return []
    # Mismo patrón que `template_file()`: un fichero cuyo nombre NO es un slug válido (mayúsculas, espacios...) se
    # omite del listado en vez de mostrarse y luego rechazarse al intentar cargarlo por ese mismo nombre (AUDIT_CODE).
    return sorted(path.stem for path in directory.glob(f"*{TEMPLATE_FILE_EXTENSION}") if path.is_file() and _TEMPLATE_NAME_PATTERN.match(path.stem))


#: Todo lo que `str.splitlines()` (usado al parsear) trata como salto de línea.
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")


class _TemplateDumper(yaml.SafeDumper):
    """`SafeDumper` que escribe entre comillas dobles (con escapes) toda cadena con un salto de línea."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = '"' if any(char in _LINE_BREAKS for char in data) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_TemplateDumper.add_representer(str, _represent_str)


def _extract_front_matter(raw: str, source: str) -> str:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise TaxonomyTemplateError(f"'{source}' debe empezar con el delimitador de front matter YAML ('---').")
    try:
        closing_index = lines.index(_FRONT_MATTER_DELIMITER, 1)
    except ValueError as exc:
        raise TaxonomyTemplateError(f"'{source}' no cierra el front matter YAML (falta un segundo '---').") from exc
    return "\n".join(lines[1:closing_index])


def _parse_front_matter(front_matter: str, source: str) -> TaxonomyManifest:
    try:
        payload = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise TaxonomyTemplateError(f"El front matter YAML de '{source}' no es válido: {exc}") from exc
    if not isinstance(payload, dict):
        raise TaxonomyTemplateError(f"El front matter de '{source}' debe ser un mapeo YAML con 'domains'/'material_types'.")
    try:
        return TaxonomyManifest.model_validate(payload)
    except ValidationError as exc:
        raise TaxonomyTemplateError(f"El front matter de '{source}' no cumple el schema de taxonomía: {exc}") from exc


__all__ = [
    "TEMPLATE_FILE_EXTENSION",
    "list_builtin_templates",
    "load_builtin_template",
    "parse_taxonomy_template",
    "render_taxonomy_template",
]
