"""Tests de MkDocsGenerator (config mkdocs.yml + index.md)."""

from datetime import UTC, datetime

import pytest
import yaml

from doc_organize.context.mkdocs_generator import MkDocsGenerator
from doc_organize.core.models import Context, Domain, DomainDocument, Project


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _make_context(project: Project, domains: list[Domain]) -> Context:
    now = datetime.now(UTC).isoformat()
    return Context(project_name=project.name, domains=domains, created_at=now, updated_at=now)


@pytest.mark.asyncio
async def test_generate_writes_valid_yaml_with_nav_grouped_by_domain(tmp_path):
    project = _make_project(tmp_path)
    document = DomainDocument(
        source_path="/docs/x.pdf",
        markdown_path="/out/x.md",
        json_path="/out/x.json",
        title="Informe X",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])

    mkdocs_yml_path = await MkDocsGenerator().generate(project, context)

    config = yaml.safe_load(mkdocs_yml_path.read_text(encoding="utf-8"))
    assert config["docs_dir"] == "organizado"
    assert config["nav"][0] == {"Inicio": "index.md"}
    assert config["nav"][1] == {"Calidad": [{"Informe X": "calidad/pdf/x/x.md"}]}


@pytest.mark.asyncio
async def test_generate_writes_index_md_listing_domains(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad")])

    await MkDocsGenerator().generate(project, context)

    index_content = (tmp_path / "organizado" / "index.md").read_text(encoding="utf-8")
    assert "Calidad" in index_content


@pytest.mark.asyncio
async def test_generate_handles_empty_context_without_crashing(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    mkdocs_yml_path = await MkDocsGenerator().generate(project, context)

    config = yaml.safe_load(mkdocs_yml_path.read_text(encoding="utf-8"))
    assert config["nav"] == [{"Inicio": "index.md"}]
