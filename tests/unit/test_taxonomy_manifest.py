"""Tests de load_taxonomy_manifest (carga del front matter de taxonomy_manifest.md)."""

from datetime import UTC, datetime

import pytest

from doc_organize.context.taxonomy_manifest import MANIFEST_FILE_NAME, load_taxonomy_manifest, render_taxonomy_manifest_markdown
from doc_organize.core.exceptions import TaxonomyManifestError
from doc_organize.core.models import Project, TaxonomyCatalogEntry, TaxonomyManifest

_VALID_FRONT_MATTER = """---
domains:
  - slug: ciberseguridad
    name: Ciberseguridad
    description: Normas de seguridad de la información
    keywords: [iso27001, ens]
  - slug: calidad
    name: Calidad
material_types:
  - slug: normativa
    name: Normativa
  - slug: procedimiento
    name: Procedimiento
---

# Taxonomía del SGI

Prosa libre, tablas y diagramas Mermaid a discreción — no se parsea.
"""


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


@pytest.mark.asyncio
async def test_returns_none_when_project_has_no_manifest(tmp_path):
    project = _make_project(tmp_path)

    assert await load_taxonomy_manifest(project) is None


@pytest.mark.asyncio
async def test_loads_domains_and_material_types_from_front_matter(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text(_VALID_FRONT_MATTER, encoding="utf-8")

    manifest = await load_taxonomy_manifest(project)

    assert manifest is not None
    assert [entry.slug for entry in manifest.domains] == ["ciberseguridad", "calidad"]
    assert manifest.domains[0].description == "Normas de seguridad de la información"
    assert manifest.domains[0].keywords == ["iso27001", "ens"]
    assert [entry.slug for entry in manifest.material_types] == ["normativa", "procedimiento"]


@pytest.mark.asyncio
async def test_raises_when_file_does_not_start_with_front_matter_delimiter(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text("# Sin front matter\n", encoding="utf-8")

    with pytest.raises(TaxonomyManifestError, match="delimitador"):
        await load_taxonomy_manifest(project)


@pytest.mark.asyncio
async def test_raises_when_front_matter_is_not_closed(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text("---\ndomains: []\n", encoding="utf-8")

    with pytest.raises(TaxonomyManifestError, match="no cierra"):
        await load_taxonomy_manifest(project)


@pytest.mark.asyncio
async def test_raises_when_front_matter_yaml_is_invalid(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text("---\ndomains: [unclosed\n---\n", encoding="utf-8")

    with pytest.raises(TaxonomyManifestError, match="no es válido"):
        await load_taxonomy_manifest(project)


@pytest.mark.asyncio
async def test_raises_when_front_matter_is_not_a_mapping(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text("---\n- solo una lista\n---\n", encoding="utf-8")

    with pytest.raises(TaxonomyManifestError, match="mapeo YAML"):
        await load_taxonomy_manifest(project)


@pytest.mark.asyncio
async def test_raises_when_domains_catalog_is_empty(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text("---\ndomains: []\nmaterial_types:\n  - slug: normativa\n    name: Normativa\n---\n", encoding="utf-8")

    with pytest.raises(TaxonomyManifestError, match="schema de taxonomía"):
        await load_taxonomy_manifest(project)


@pytest.mark.asyncio
async def test_raises_when_material_types_catalog_is_missing(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / MANIFEST_FILE_NAME).write_text("---\ndomains:\n  - slug: calidad\n    name: Calidad\n---\n", encoding="utf-8")

    with pytest.raises(TaxonomyManifestError, match="schema de taxonomía"):
        await load_taxonomy_manifest(project)


def _make_manifest() -> TaxonomyManifest:
    return TaxonomyManifest(
        domains=[
            TaxonomyCatalogEntry(slug="ciberseguridad", name="Ciberseguridad", description="Normas de seguridad", keywords=["iso27001"]),
            TaxonomyCatalogEntry(slug="calidad", name="Calidad"),
        ],
        material_types=[TaxonomyCatalogEntry(slug="normativa", name="Normativa"), TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento")],
    )


@pytest.mark.asyncio
async def test_render_taxonomy_manifest_markdown_produces_a_loadable_front_matter(tmp_path) -> None:
    """El texto renderizado debe poder recargarse tal cual con `load_taxonomy_manifest()` --
    mismo formato de fichero (front matter YAML delimitado por '---' + prosa libre)."""
    text = render_taxonomy_manifest_markdown(
        _make_manifest(), reasoning="Dos áreas temáticas claras", sample_document_count=5, total_document_count=20
    )
    (tmp_path / MANIFEST_FILE_NAME).write_text(text, encoding="utf-8")
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())

    manifest = await load_taxonomy_manifest(project)

    assert manifest is not None
    assert [entry.slug for entry in manifest.domains] == ["ciberseguridad", "calidad"]
    assert manifest.domains[0].keywords == ["iso27001"]
    assert [entry.slug for entry in manifest.material_types] == ["normativa", "procedimiento"]


def test_render_taxonomy_manifest_markdown_includes_sample_coverage_and_reasoning() -> None:
    text = render_taxonomy_manifest_markdown(
        _make_manifest(), reasoning="Dos áreas temáticas claras", sample_document_count=5, total_document_count=20
    )

    assert "muestra de 5 de 20 documentos" in text
    assert "Dos áreas temáticas claras" in text
    assert "Ciberseguridad, Calidad" in text
    assert "Normativa, Procedimiento" in text


def test_render_taxonomy_manifest_markdown_without_reasoning_omits_it_gracefully() -> None:
    text = render_taxonomy_manifest_markdown(_make_manifest(), reasoning=None, sample_document_count=5, total_document_count=20)

    assert text.startswith("---\ndomains:")
    assert "| Dominio | Ciberseguridad, Calidad |" in text
