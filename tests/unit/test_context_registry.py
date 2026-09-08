"""Tests de ContextRegistry (persistencia de context.json + domains/)."""

import json

from datetime import UTC, datetime

import pytest

from doc_organize.context.context_registry import ContextRegistry
from doc_organize.core.exceptions import ContextError, ContextNotFoundError, DomainNotFoundError
from doc_organize.core.models import Context, Domain, DomainDocument, Project


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _make_context(project: Project, domains: list[Domain]) -> Context:
    now = datetime.now(UTC).isoformat()
    return Context(project_name=project.name, domains=domains, created_at=now, updated_at=now)


@pytest.mark.asyncio
async def test_load_context_raises_when_not_built(tmp_path):
    project = _make_project(tmp_path)
    registry = ContextRegistry()

    with pytest.raises(ContextNotFoundError):
        await registry.load_context(project)


@pytest.mark.asyncio
async def test_save_and_load_roundtrip_preserves_domain_documents(tmp_path):
    project = _make_project(tmp_path)
    document = DomainDocument(
        source_path="/docs/x.pdf",
        markdown_path="/out/x.md",
        json_path="/out/x.json",
        title="X",
        document_type="pdf",
        confidence=0.9,
    )
    domain = Domain(slug="calidad", name="Calidad", documents=[document])
    context = _make_context(project, [domain])
    registry = ContextRegistry()

    await registry.save_context(project, context)
    loaded = await registry.load_context(project)

    assert loaded.project_name == "Demo"
    assert len(loaded.domains) == 1
    assert loaded.domains[0].slug == "calidad"
    assert loaded.domains[0].documents[0].title == "X"


@pytest.mark.asyncio
async def test_get_domain_raises_when_missing(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad")])
    registry = ContextRegistry()
    await registry.save_context(project, context)

    with pytest.raises(DomainNotFoundError):
        await registry.get_domain(project, "inexistente")


@pytest.mark.asyncio
async def test_domain_md_preserves_hand_edited_sections_on_rebuild(tmp_path):
    project = _make_project(tmp_path)
    registry = ContextRegistry()
    context = _make_context(project, [Domain(slug="calidad", name="Calidad")])
    await registry.save_context(project, context)

    domain_md = tmp_path / "domains" / "calidad" / "DOMAIN.md"
    edited = domain_md.read_text(encoding="utf-8").replace(
        "## Descripción\n*No aplica a este dominio.*", "## Descripción\nGestión de calidad ISO 9001."
    )
    domain_md.write_text(edited, encoding="utf-8")

    document = DomainDocument(
        source_path="/docs/y.pdf", markdown_path="/out/y.md", json_path="/out/y.json", title="Y", document_type="pdf", confidence=0.8
    )
    context_v2 = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])
    await registry.save_context(project, context_v2)

    final_text = domain_md.read_text(encoding="utf-8")
    assert "Gestión de calidad ISO 9001." in final_text
    assert "`Y`" in final_text


@pytest.mark.asyncio
async def test_rebuild_removes_stale_domain_dirs_not_in_new_context(tmp_path):
    project = _make_project(tmp_path)
    registry = ContextRegistry()

    await registry.save_context(project, _make_context(project, [Domain(slug="ciberseguridad", name="Ciberseguridad")]))
    assert (tmp_path / "domains" / "ciberseguridad").is_dir()

    await registry.save_context(project, _make_context(project, [Domain(slug="calidad", name="Calidad")]))

    assert not (tmp_path / "domains" / "ciberseguridad").exists()
    assert (tmp_path / "domains" / "calidad").is_dir()


@pytest.mark.asyncio
async def test_load_wraps_schema_mismatch_in_context_json_as_context_error(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / "context.json").write_text(json.dumps({"project_name": "Demo", "domains": []}), encoding="utf-8")

    with pytest.raises(ContextError):
        await ContextRegistry().load_context(project)


@pytest.mark.asyncio
async def test_load_wraps_schema_mismatch_in_domain_index_as_context_error(tmp_path):
    project = _make_project(tmp_path)
    registry = ContextRegistry()
    await registry.save_context(project, _make_context(project, [Domain(slug="calidad", name="Calidad")]))

    index_path = tmp_path / "domains" / "calidad" / "index.json"
    index_path.write_text(json.dumps({"documents": [{"title": "sin los demás campos obligatorios"}]}), encoding="utf-8")

    with pytest.raises(ContextError):
        await registry.load_context(project)
