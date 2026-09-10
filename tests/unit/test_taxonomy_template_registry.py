"""Tests de TaxonomyTemplateRegistry (biblioteca de plantillas de manifiesto de taxonomía)."""

import pytest

from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry
from doc_organize.core.exceptions import TaxonomyTemplateError

_USER_TEMPLATE = """---
title: Plantilla de Usuario
description: Una plantilla creada por el usuario, fuera del paquete.
domains:
  - slug: dominio-usuario
    name: Dominio Usuario
material_types:
  - slug: registro
    name: Registro
---

Prosa libre, no se parsea.
"""

_INVALID_TEMPLATE = "# Sin front matter\n"


@pytest.mark.asyncio
async def test_list_templates_includes_the_two_builtin_templates(tmp_path):
    registry = TaxonomyTemplateRegistry(tmp_path / "no-existe-todavia")

    summaries = await registry.list_templates()

    names = [summary.name for summary in summaries]
    assert names == sorted(names)
    assert "sgi-iso27001" in names
    assert "calidad" in names
    sgi = next(summary for summary in summaries if summary.name == "sgi-iso27001")
    assert sgi.title == "SGI ISO 27001"
    assert sgi.description is not None


@pytest.mark.asyncio
async def test_list_templates_includes_user_template_alongside_builtin(tmp_path):
    (tmp_path / "propia.md").write_text(_USER_TEMPLATE, encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    summaries = await registry.list_templates()

    names = {summary.name for summary in summaries}
    assert names == {"sgi-iso27001", "calidad", "propia"}
    propia = next(summary for summary in summaries if summary.name == "propia")
    assert propia.title == "Plantilla de Usuario"
    assert propia.description == "Una plantilla creada por el usuario, fuera del paquete."


@pytest.mark.asyncio
async def test_list_templates_user_override_replaces_builtin_of_same_name(tmp_path):
    (tmp_path / "calidad.md").write_text(_USER_TEMPLATE.replace("Plantilla de Usuario", "Calidad Personalizada"), encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    summaries = await registry.list_templates()

    calidad = next(summary for summary in summaries if summary.name == "calidad")
    assert calidad.title == "Calidad Personalizada"


@pytest.mark.asyncio
async def test_list_templates_skips_user_template_with_invalid_name(tmp_path):
    """Un fichero cuyo nombre no es un slug válido (mayúsculas) nunca debe aparecer
    listado — si apareciera, seleccionarlo fallaría en `load_template()` con el mismo
    nombre exacto que el listado ofreció, una experiencia confusa."""
    (tmp_path / "Plantilla Invalida.md").write_text(_USER_TEMPLATE, encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    summaries = await registry.list_templates()

    assert "Plantilla Invalida" not in {summary.name for summary in summaries}


@pytest.mark.asyncio
async def test_list_templates_skips_malformed_user_template(tmp_path):
    (tmp_path / "rota.md").write_text(_INVALID_TEMPLATE, encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    summaries = await registry.list_templates()

    assert "rota" not in {summary.name for summary in summaries}
    assert "sgi-iso27001" in {summary.name for summary in summaries}


@pytest.mark.asyncio
async def test_load_template_returns_builtin_manifest(tmp_path):
    registry = TaxonomyTemplateRegistry(tmp_path / "no-existe-todavia")

    manifest = await registry.load_template("sgi-iso27001")

    assert manifest.title == "SGI ISO 27001"
    assert "gobierno-seguridad" in [entry.slug for entry in manifest.domains]
    assert "politica" in [entry.slug for entry in manifest.material_types]


@pytest.mark.asyncio
async def test_load_template_user_override_takes_priority_over_builtin(tmp_path):
    (tmp_path / "calidad.md").write_text(_USER_TEMPLATE, encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    manifest = await registry.load_template("calidad")

    assert manifest.title == "Plantilla de Usuario"
    assert [entry.slug for entry in manifest.domains] == ["dominio-usuario"]


@pytest.mark.asyncio
async def test_load_template_raises_for_unknown_name(tmp_path):
    registry = TaxonomyTemplateRegistry(tmp_path)

    with pytest.raises(TaxonomyTemplateError, match="No existe"):
        await registry.load_template("no-existe-esta-plantilla")


@pytest.mark.asyncio
async def test_load_template_rejects_path_traversal_name(tmp_path):
    registry = TaxonomyTemplateRegistry(tmp_path)

    with pytest.raises(TaxonomyTemplateError, match="no es un nombre de plantilla válido"):
        await registry.load_template("../secreto")


@pytest.mark.asyncio
async def test_load_template_rejects_malformed_front_matter(tmp_path):
    (tmp_path / "rota.md").write_text(_INVALID_TEMPLATE, encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    with pytest.raises(TaxonomyTemplateError, match="delimitador"):
        await registry.load_template("rota")
