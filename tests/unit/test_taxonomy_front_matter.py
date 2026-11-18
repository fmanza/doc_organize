"""Manifiesto 2.0 por ejes (A1): formato `schema: 2`, migración de 1.x, informe del front matter y límites."""

import pytest
import yaml

from doc_organize import inspect_taxonomy_front_matter, migrate_manifest_v1, parse_taxonomy_template, render_taxonomy_template
from doc_organize.core.exceptions import TaxonomyManifestError, TaxonomyTemplateError
from doc_organize.core.models import (
    TAXONOMY_MAX_AXES,
    TAXONOMY_MAX_ENTRIES_PER_AXIS,
    TaxonomyAxis,
    TaxonomyEntry,
    TaxonomyManifest,
    TaxonomyManifestDraftResult,
)
from tests.unit.taxonomy_helpers import two_axis_manifest

#: Forma de la plantilla de CALIDAD_VD (1.x, formato implícito): ejes como claves de nivel superior, entradas con
#: campos extra (`version`, `url`) y prosa en el cuerpo.
IMPLICIT_V1 = """---
title: Normas y gobernanza
description: >
  Varios ejes.
domains:
  - slug: cumplimiento-legal
    name: Cumplimiento legal
    keywords: [ley, normativa]
management_system:
  - slug: sgsi
    name: SGSI
normative_frameworks:
  - slug: iso-27001
    name: ISO/IEC 27001
    version: "2022"
    keywords: [SGSI, seguridad]
  - slug: ens
    name: ENS - Esquema Nacional de Seguridad
    url: "https://www.ccn.cni.es/"
    keywords: [ENS, seguridad, administración pública]
material_types:
  - slug: politica
    name: Política
evidence:
  - slug: evidencia-registro
    name: Registro de evidencia
notas_internas: texto libre
referencias: [uno, dos]
---

# Taxonomía

Prosa que no se parsea.
"""


def _entry(slug: str) -> TaxonomyEntry:
    return TaxonomyEntry(slug=slug, name=slug.title())


def _axis(key: str, organizes: str | None = None, entries: int = 1, **kwargs: object) -> TaxonomyAxis:
    return TaxonomyAxis(key=key, name=key, organizes=organizes, entries=[_entry(f"{key}-{i}") for i in range(entries)], **kwargs)  # type: ignore[arg-type]


# --- Modelo -------------------------------------------------------------------------------------------------------


def test_manifest_exposes_its_organizing_and_tag_axes() -> None:
    frameworks = _axis("normative_frameworks", multiple=True)
    manifest = two_axis_manifest([_entry("calidad")], [_entry("politica")], extra_axes=[frameworks])

    assert manifest.schema_version == 2
    assert manifest.folder_axis.key == "domains"
    assert manifest.subfolder_axis.key == "material_types"
    assert manifest.tag_axes == [frameworks]
    assert manifest.axis("normative_frameworks") is frameworks
    assert manifest.axis("no-existe") is None


@pytest.mark.parametrize(
    ("axes", "message"),
    [
        ([_axis("material_types", "subfolder")], "organizes: folder"),
        ([_axis("domains", "folder")], "organizes: subfolder"),
        ([_axis("a", "folder"), _axis("b", "folder"), _axis("c", "subfolder")], "hay 2: a, b"),
        ([_axis("a", "folder"), _axis("a", "subfolder")], "claves de eje repetidas: a"),
        ([_axis("d", "folder"), _axis("m", "subfolder"), *[_axis(f"x{i}") for i in range(TAXONOMY_MAX_AXES - 1)]], "como mucho 10 ejes"),
    ],
)
def test_manifest_rejects_invalid_axis_sets(axes: list[TaxonomyAxis], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        TaxonomyManifest(axes=axes)


def test_axis_limits_and_rules() -> None:
    with pytest.raises(ValueError, match="como mucho 150 entradas"):
        _axis("x", entries=TAXONOMY_MAX_ENTRIES_PER_AXIS + 1)
    with pytest.raises(ValueError, match="al menos una entrada"):
        TaxonomyAxis(key="x", name="X", entries=[])
    with pytest.raises(ValueError, match="no puede ser de varios valores"):
        _axis("x", "folder", multiple=True)
    with pytest.raises(ValueError, match="necesita reglas"):
        _axis("x", "subfolder", rules=False)
    with pytest.raises(ValueError, match="pattern"):
        _axis("Marcos-Normativos")
    with pytest.raises(ValueError, match="500"):
        TaxonomyEntry(slug="a", name="A", description="x" * 501)
    assert len(_axis("x", entries=TAXONOMY_MAX_ENTRIES_PER_AXIS).entries) == TAXONOMY_MAX_ENTRIES_PER_AXIS


def test_draft_result_becomes_a_two_axis_manifest() -> None:
    draft = TaxonomyManifestDraftResult(domains=[_entry("calidad")], material_types=[_entry("politica")])

    manifest = draft.to_manifest()

    assert [(axis.key, axis.organizes) for axis in manifest.axes] == [("domains", "folder"), ("material_types", "subfolder")]


# --- Lectura de 1.x -------------------------------------------------------------------------------------------------


def test_v1_implicit_template_reads_every_entry_list_as_an_axis() -> None:
    manifest = parse_taxonomy_template(IMPLICIT_V1)

    assert [axis.key for axis in manifest.axes] == ["domains", "material_types", "management_system", "normative_frameworks", "evidence"]
    assert manifest.folder_axis.entries[0].slug == "cumplimiento-legal"
    assert manifest.subfolder_axis.entries[0].slug == "politica"
    frameworks = manifest.axis("normative_frameworks")
    assert frameworks is not None
    assert frameworks.name == "Normative frameworks"
    assert frameworks.multiple is True
    assert frameworks.organizes is None
    assert [entry.slug for entry in frameworks.entries] == ["iso-27001", "ens"]
    assert frameworks.entries[1].keywords == ["ENS", "seguridad", "administración pública"]
    assert manifest.title == "Normas y gobernanza"


def test_v1_explicit_facets_block_keeps_its_options() -> None:
    text = """---
domains: [{slug: a, name: A}]
material_types: [{slug: m, name: M}]
facets:
  normative_frameworks:
    name: Marcos normativos
    threshold: 0.5
    entries: [{slug: ens, name: ENS}]
  evidence:
    name: Evidencias
    multiple: false
    rules: false
    entries: [{slug: registro, name: Registro}]
---
"""
    manifest = parse_taxonomy_template(text)

    frameworks, evidence = manifest.tag_axes
    assert (frameworks.key, frameworks.name, frameworks.multiple, frameworks.threshold) == ("normative_frameworks", "Marcos normativos", True, 0.5)
    assert (evidence.multiple, evidence.rules) == (False, False)


def test_v1_two_list_manifest_reads_like_1_6() -> None:
    manifest = parse_taxonomy_template("---\ndomains: [{slug: a, name: A}]\nmaterial_types: [{slug: m, name: M}]\n---\n")

    assert [axis.key for axis in manifest.axes] == ["domains", "material_types"]
    assert manifest.tag_axes == []


def test_v1_without_material_types_explains_what_is_missing() -> None:
    with pytest.raises(TaxonomyTemplateError, match="organizes: subfolder"):
        parse_taxonomy_template("---\ndomains: [{slug: a, name: A}]\n---\n")


# --- Migración ------------------------------------------------------------------------------------------------------


def test_migrate_keeps_the_body_the_extra_fields_and_the_unused_keys() -> None:
    migrated = migrate_manifest_v1(IMPLICIT_V1)

    front, body = migrated.split("\n---\n", 1)
    payload = yaml.safe_load(front.removeprefix("---\n"))
    assert payload["schema"] == 2
    assert [axis["key"] for axis in payload["axes"]] == ["domains", "material_types", "management_system", "normative_frameworks", "evidence"]
    assert payload["axes"][3]["entries"][0]["version"] == "2022"  # campos extra de la entrada, intactos
    assert payload["notas_internas"] == "texto libre"
    assert payload["referencias"] == ["uno", "dos"]
    assert body == "\n# Taxonomía\n\nProsa que no se parsea.\n"
    assert parse_taxonomy_template(migrated) == parse_taxonomy_template(IMPLICIT_V1)


def test_migrate_returns_a_v2_text_unchanged() -> None:
    text = render_taxonomy_template(two_axis_manifest([_entry("a")], [_entry("m")]), "# Cuerpo\n")

    assert migrate_manifest_v1(text) == text


def test_unknown_schema_version_is_rejected() -> None:
    with pytest.raises(TaxonomyManifestError, match="schema: 3"):
        migrate_manifest_v1("---\nschema: 3\naxes: []\n---\n")
    with pytest.raises(TaxonomyTemplateError, match="schema: 3"):
        parse_taxonomy_template("---\nschema: 3\naxes: []\n---\n")


# --- Informe ---------------------------------------------------------------------------------------------------------


def test_inspect_reports_implicit_axes_and_ignored_keys_of_a_v1_text() -> None:
    report = inspect_taxonomy_front_matter(IMPLICIT_V1)

    assert report.legacy_format is True
    assert report.axes == ["domains", "material_types", "management_system", "normative_frameworks", "evidence"]
    assert report.implicit_axes == ["management_system", "normative_frameworks", "evidence"]
    assert report.ignored_keys == ["notas_internas", "referencias"]


def test_inspect_reports_ignored_keys_of_a_v2_text() -> None:
    text = render_taxonomy_template(two_axis_manifest([_entry("a")], [_entry("m")])).replace("schema: 2\n", "schema: 2\ndomains: viejo\n")

    report = inspect_taxonomy_front_matter(text)

    assert (report.legacy_format, report.implicit_axes, report.ignored_keys) == (False, [], ["domains"])
    assert report.axes == ["domains", "material_types"]


def test_inspect_does_not_read_an_invalid_key_as_an_axis() -> None:
    report = inspect_taxonomy_front_matter("---\ndomains: []\nMarcos-Normativos:\n  - {slug: ens, name: ENS}\n---\n")

    assert report.implicit_axes == []
    assert report.ignored_keys == ["Marcos-Normativos"]


# --- Escritura -------------------------------------------------------------------------------------------------------


def test_render_writes_v2_without_default_options_and_round_trips() -> None:
    frameworks = TaxonomyAxis(
        key="normative_frameworks",
        name="Marcos normativos",
        description="Normas aplicables\n---\ncon saltos",
        multiple=True,
        threshold=0.4,
        entries=[TaxonomyEntry(slug="ens", name="ENS", keywords=["Esquema Nacional de Seguridad"], examples=["Declaración de aplicabilidad"])],
    )
    manifest = two_axis_manifest([_entry("a")], [_entry("m")], title="T", extra_axes=[frameworks])

    text = render_taxonomy_template(manifest)

    payload = yaml.safe_load(text.split("---\n")[1])
    assert payload["axes"][0] == {"key": "domains", "name": "Dominios", "organizes": "folder", "entries": [{"slug": "a", "name": "A"}]}
    assert list(payload["axes"][2]) == ["key", "name", "description", "multiple", "threshold", "entries"]
    assert parse_taxonomy_template(text) == manifest
