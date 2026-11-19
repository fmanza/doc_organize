"""
Front matter de un manifiesto o una plantilla de taxonomía: lectura, migración de 1.x a 2.0 e informe (2.0.0, A1).

Formato 2.0 (`schema: 2`)::

    ---
    schema: 2
    title: Normas y gobernanza
    axes:
      - key: domains
        name: Dominios
        organizes: folder
        entries:
          - slug: cumplimiento-legal
            name: Cumplimiento legal
      - key: material_types
        name: Tipos de material
        organizes: subfolder
        entries: [...]
      - key: normative_frameworks
        name: Marcos normativos
        multiple: true
        entries: [...]
    ---
    Prosa libre (no se parsea).

Un front matter de 1.x (sin `schema`) se migra al leerlo, sin tocar el fichero: `domains` pasa a ser el eje que
organiza la carpeta, `material_types` el de la subcarpeta, cada faceta del bloque `facets:` un eje, y cada clave de
nivel superior cuyo valor sea una lista de entradas `{slug, name}` (formato implícito, decisión D1) un eje de varios
valores. Las claves que no se usan se conservan en el texto migrado y se informan en `ignored_keys`.
"""

import re

from collections.abc import Callable
from typing import Any

import yaml

from pydantic import ValidationError

from doc_organize.context.project_profile import parse_profile
from doc_organize.core.exceptions import TaxonomyManifestError
from doc_organize.core.models import TAXONOMY_AXIS_KEY_PATTERN, TaxonomyAxis, TaxonomyFrontMatterReport, TaxonomyManifest

FRONT_MATTER_DELIMITER = "---"
SCHEMA_VERSION = 2

#: Claves de nivel superior que entiende el formato 2.0.
_V2_KEYS = ("schema", "title", "description", "axes")
#: Claves de nivel superior con significado propio en 1.x (no se leen como ejes implícitos).
_V1_KEYS = ("title", "description", "domains", "material_types", "facets")
_AXIS_KEY = re.compile(TAXONOMY_AXIS_KEY_PATTERN)

#: Todo lo que `str.splitlines()` (usado al parsear) trata como salto de línea.
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")

ErrorFactory = Callable[[str], Exception]


def split_front_matter(text: str, source: str, error: ErrorFactory) -> tuple[str, str]:
    """Separa `text` en el YAML del front matter y el cuerpo que le sigue.

    Raises:
        Exception: La que construye `error` si falta el delimitador inicial o el de cierre.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        raise error(f"'{source}' debe empezar con el delimitador de front matter YAML ('---').")
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == FRONT_MATTER_DELIMITER:
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise error(f"'{source}' no cierra el front matter YAML (falta un segundo '---').")


def load_front_matter_payload(text: str, source: str, error: ErrorFactory) -> tuple[dict[str, Any], str]:
    """El front matter de `text` como mapeo YAML, y el cuerpo.

    Raises:
        Exception: La que construye `error` si el front matter falta, no es YAML válido o no es un mapeo.
    """
    front_matter, body = split_front_matter(text, source, error)
    try:
        payload = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise error(f"El front matter YAML de '{source}' no es válido: {exc}") from exc
    if not isinstance(payload, dict):
        raise error(f"El front matter de '{source}' debe ser un mapeo YAML con 'schema: 2' y 'axes'.")
    return payload, body


def is_legacy_payload(payload: dict[str, Any], source: str, error: ErrorFactory) -> bool:
    """`True` si `payload` es un front matter de 1.x (sin `schema`).

    Raises:
        Exception: La que construye `error` si declara un `schema` distinto de 2.
    """
    if "schema" not in payload:
        return True
    if payload["schema"] != SCHEMA_VERSION:
        raise error(
            f"El front matter de '{source}' declara 'schema: {payload['schema']}'; esta versión de doc_organize lee 'schema: 2' (y 1.x sin 'schema')."
        )
    return False


def migrate_payload_v1(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Convierte un front matter de 1.x en uno de 2.0; devuelve también las claves leídas como ejes implícitos.

    Conserva las entradas tal cual (con sus campos extra) y, al final, las claves que no se usan.
    """
    axes: list[dict[str, Any]] = []
    if "domains" in payload:
        axes.append({"key": "domains", "name": "Dominios", "organizes": "folder", "entries": payload["domains"]})
    if "material_types" in payload:
        axes.append({"key": "material_types", "name": "Tipos de material", "organizes": "subfolder", "entries": payload["material_types"]})
    facets = payload.get("facets")
    if isinstance(facets, dict):
        for key, spec in facets.items():
            axes.append(_facet_axis(str(key), spec))
    implicit: list[str] = []
    ignored: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _V1_KEYS:
            if key == "facets" and not isinstance(value, dict):
                ignored[key] = value
            continue
        if _is_entry_list(value) and _AXIS_KEY.match(str(key)):
            axes.append({"key": key, "name": _name_from_key(str(key)), "multiple": True, "entries": value})
            implicit.append(str(key))
        else:
            ignored[key] = value
    migrated: dict[str, Any] = {"schema": SCHEMA_VERSION}
    for key in ("title", "description"):
        if key in payload:
            migrated[key] = payload[key]
    migrated["axes"] = axes
    migrated.update(ignored)
    return migrated, implicit


def manifest_from_text(text: str, source: str, error: ErrorFactory) -> TaxonomyManifest:
    """Lee y valida el front matter de `text` (2.0, o 1.x migrado en memoria) como `TaxonomyManifest`.

    Raises:
        Exception: La que construye `error` ante cualquier problema de formato o de schema, con el motivo.
    """
    payload, body = load_front_matter_payload(text, source, error)
    if is_legacy_payload(payload, source, error):
        payload, _ = migrate_payload_v1(payload)
    try:
        manifest = TaxonomyManifest.model_validate({key: payload[key] for key in _V2_KEYS if key in payload})
    except ValidationError as exc:
        raise error(f"El front matter de '{source}' no cumple el schema de taxonomía: {_describe(exc)}") from exc
    # El perfil del proyecto (2.0.0, G2) son secciones del cuerpo, no del front matter.
    profile = parse_profile(body)
    return manifest.model_copy(update={"profile": profile}) if profile is not None else manifest


def migrate_manifest_v1(text: str) -> str:
    """Reescribe un manifiesto o una plantilla de 1.x en el formato 2.0 (`schema: 2`, `axes:`), conservando el cuerpo.

    Un texto que ya es 2.0 se devuelve tal cual. No valida el resultado: para eso, `parse_taxonomy_template`.

    Raises:
        TaxonomyManifestError: El front matter falta, no es YAML válido o declara un `schema` desconocido.

    Example:
        >>> text = "---\\ndomains:\\n  - slug: calidad\\n    name: Calidad\\n---\\n# Notas\\n"
        >>> print(migrate_manifest_v1(text))
        ---
        schema: 2
        axes:
        - key: domains
          name: Dominios
          organizes: folder
          entries:
          - slug: calidad
            name: Calidad
        ---
        # Notas
        <BLANKLINE>
    """
    payload, body = load_front_matter_payload(text, "<texto>", TaxonomyManifestError)
    if not is_legacy_payload(payload, "<texto>", TaxonomyManifestError):
        return text
    migrated, _ = migrate_payload_v1(payload)
    return f"{FRONT_MATTER_DELIMITER}\n{dump_yaml(migrated)}{FRONT_MATTER_DELIMITER}\n{body}"


def inspect_taxonomy_front_matter(text: str) -> TaxonomyFrontMatterReport:
    """Qué ejes se leerán de `text`, cuáles salen del formato implícito de 1.x y qué claves se ignoran.

    No valida los ejes (para eso, `parse_taxonomy_template`): sirve para avisar al autor al guardar.

    Raises:
        TaxonomyManifestError: El front matter falta, no es YAML válido o declara un `schema` desconocido.

    Example:
        >>> report = inspect_taxonomy_front_matter(
        ...     "---\\ndomains: []\\nmaterial_types: []\\nnormative_frameworks:\\n"
        ...     "  - slug: ens\\n    name: ENS\\nnotas: libre\\n---\\n"
        ... )
        >>> report.legacy_format, report.implicit_axes, report.ignored_keys
        (True, ['normative_frameworks'], ['notas'])
    """
    payload, _ = load_front_matter_payload(text, "<texto>", TaxonomyManifestError)
    legacy = is_legacy_payload(payload, "<texto>", TaxonomyManifestError)
    implicit: list[str] = []
    if legacy:
        payload, implicit = migrate_payload_v1(payload)
    axes = payload.get("axes")
    keys = [str(axis.get("key")) for axis in axes if isinstance(axis, dict)] if isinstance(axes, list) else []
    return TaxonomyFrontMatterReport(
        axes=keys,
        implicit_axes=implicit,
        ignored_keys=[str(key) for key in payload if key not in _V2_KEYS],
        legacy_format=legacy,
    )


def manifest_payload(manifest: TaxonomyManifest) -> dict[str, Any]:
    """`manifest` como front matter 2.0 (sin valores por defecto de los ejes, para que se lea bien)."""
    payload: dict[str, Any] = {"schema": SCHEMA_VERSION}
    if manifest.title is not None:
        payload["title"] = manifest.title
    if manifest.description is not None:
        payload["description"] = manifest.description
    payload["axes"] = [_axis_payload(axis) for axis in manifest.axes]
    return payload


class _TemplateDumper(yaml.SafeDumper):
    """`SafeDumper` que escribe entre comillas dobles (con escapes) toda cadena con un salto de línea."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = '"' if any(char in _LINE_BREAKS for char in data) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_TemplateDumper.add_representer(str, _represent_str)


def dump_yaml(payload: dict[str, Any]) -> str:
    """YAML del front matter: sin plegar líneas y con los saltos de línea escapados.

    Así ninguna línea puede ser un `---` que cierre el front matter antes de tiempo ni partirse distinto al releerla
    con `splitlines()`.
    """
    return yaml.dump(payload, Dumper=_TemplateDumper, allow_unicode=True, sort_keys=False, width=float("inf"))


def render_front_matter(manifest: TaxonomyManifest) -> str:
    """El front matter 2.0 de `manifest`, con sus delimitadores."""
    return f"{FRONT_MATTER_DELIMITER}\n{dump_yaml(manifest_payload(manifest))}{FRONT_MATTER_DELIMITER}\n"


def _axis_payload(axis: TaxonomyAxis) -> dict[str, Any]:
    """Un eje en el orden en que se lee mejor: clave, nombre, opciones distintas del valor por defecto y entradas."""
    options = axis.model_dump(exclude_defaults=True, exclude={"key", "name", "entries"})
    entries = [entry.model_dump(exclude_defaults=True) for entry in axis.entries]
    return {"key": axis.key, "name": axis.name, **options, "entries": entries}


def _facet_axis(key: str, spec: Any) -> dict[str, Any]:
    """Un eje a partir de una faceta del bloque `facets:` de 1.x (varios valores por defecto)."""
    if not isinstance(spec, dict):
        return {"key": key, "name": _name_from_key(key), "multiple": True, "entries": spec}
    axis: dict[str, Any] = {"key": key, "name": spec.get("name") or _name_from_key(key), "multiple": spec.get("multiple", True)}
    for field in ("description", "threshold", "rules"):
        if field in spec:
            axis[field] = spec[field]
    axis["entries"] = spec.get("entries")
    return axis


def _is_entry_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) and "slug" in item and "name" in item for item in value)


def _name_from_key(key: str) -> str:
    """`normative_frameworks` → «Normative frameworks»."""
    return key.replace("_", " ").capitalize()


def _describe(exc: ValidationError) -> str:
    """Los errores de Pydantic en una línea legible: `axes.2.entries: un eje admite como mucho 150 entradas`."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = str(error["msg"]).removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)


__all__ = [
    "inspect_taxonomy_front_matter",
    "migrate_manifest_v1",
]
