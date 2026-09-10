"""Tests de MkDocsGenerator (config mkdocs.yml + index.md + build del sitio)."""

import subprocess

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


def _disable_mkdocs_build(monkeypatch) -> None:
    """Los tests de config/index no necesitan invocar `mkdocs build` de verdad
    (lento, y depende de que `mkdocs` esté instalado en el entorno) — se cubre
    aparte en los tests dedicados a `_build_site`."""
    monkeypatch.setattr("doc_organize.context.mkdocs_generator.shutil.which", lambda _name: None)


@pytest.mark.asyncio
async def test_generate_writes_valid_yaml_with_nav_grouped_by_domain(tmp_path, monkeypatch):
    _disable_mkdocs_build(monkeypatch)
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

    mkdocs_yml_path, site_built = await MkDocsGenerator().generate(project, context)

    config = yaml.safe_load(mkdocs_yml_path.read_text(encoding="utf-8"))
    assert config["docs_dir"] == "organizado"
    assert config["site_dir"] == "site"
    assert config["nav"][0] == {"Inicio": "index.md"}
    assert config["nav"][1] == {"Calidad": [{"Informe X": "calidad/pdf/x/x.md"}]}
    assert site_built is False


@pytest.mark.asyncio
async def test_generate_groups_nav_by_material_type_when_taxonomy_manifest_used(tmp_path, monkeypatch):
    _disable_mkdocs_build(monkeypatch)
    project = _make_project(tmp_path)
    normativa_doc = DomainDocument(
        source_path="/docs/a.pdf",
        markdown_path="/out/a.md",
        json_path="/out/a.json",
        title="Norma A",
        document_type="pdf",
        material_type="normativa",
        confidence=0.9,
    )
    procedimiento_doc = DomainDocument(
        source_path="/docs/b.pdf",
        markdown_path="/out/b.md",
        json_path="/out/b.json",
        title="Proc B",
        document_type="pdf",
        material_type="procedimiento",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[normativa_doc, procedimiento_doc])])
    context.taxonomy_manifest_used = True

    mkdocs_yml_path, _site_built = await MkDocsGenerator().generate(project, context)

    config = yaml.safe_load(mkdocs_yml_path.read_text(encoding="utf-8"))
    assert config["nav"][1] == {
        "Calidad": [
            {"Normativa": [{"Norma A": "calidad/normativa/a/a.md"}]},
            {"Procedimiento": [{"Proc B": "calidad/procedimiento/b/b.md"}]},
        ]
    }


@pytest.mark.asyncio
async def test_generate_writes_index_md_listing_domains(tmp_path, monkeypatch):
    _disable_mkdocs_build(monkeypatch)
    project = _make_project(tmp_path)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad")])

    await MkDocsGenerator().generate(project, context)

    index_content = (tmp_path / "organizado" / "index.md").read_text(encoding="utf-8")
    assert "Calidad" in index_content


@pytest.mark.asyncio
async def test_generate_handles_empty_context_without_crashing(tmp_path, monkeypatch):
    _disable_mkdocs_build(monkeypatch)
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    mkdocs_yml_path, _site_built = await MkDocsGenerator().generate(project, context)

    config = yaml.safe_load(mkdocs_yml_path.read_text(encoding="utf-8"))
    assert config["nav"] == [{"Inicio": "index.md"}]


@pytest.mark.asyncio
async def test_generate_returns_site_built_false_when_mkdocs_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("doc_organize.context.mkdocs_generator.shutil.which", lambda _name: None)
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    _mkdocs_yml_path, site_built = await MkDocsGenerator().generate(project, context)

    assert site_built is False
    assert not (tmp_path / "site").exists()


@pytest.mark.asyncio
async def test_generate_returns_site_built_true_when_mkdocs_build_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("doc_organize.context.mkdocs_generator.shutil.which", lambda _name: "/usr/bin/mkdocs")
    monkeypatch.setattr(
        "doc_organize.context.mkdocs_generator.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    _mkdocs_yml_path, site_built = await MkDocsGenerator().generate(project, context)

    assert site_built is True


@pytest.mark.asyncio
async def test_generate_returns_site_built_false_when_mkdocs_build_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("doc_organize.context.mkdocs_generator.shutil.which", lambda _name: "/usr/bin/mkdocs")
    monkeypatch.setattr(
        "doc_organize.context.mkdocs_generator.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom"),
    )
    project = _make_project(tmp_path)
    context = _make_context(project, [])

    _mkdocs_yml_path, site_built = await MkDocsGenerator().generate(project, context)

    assert site_built is False


@pytest.mark.asyncio
async def test_delete_site_removes_mkdocs_yml_and_site_dir(tmp_path, monkeypatch):
    _disable_mkdocs_build(monkeypatch)
    project = _make_project(tmp_path)
    context = _make_context(project, [])
    generator = MkDocsGenerator()
    await generator.generate(project, context)
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text("<html></html>", encoding="utf-8")

    await generator.delete_site(project)

    assert not (tmp_path / "mkdocs.yml").exists()
    assert not (tmp_path / "site").exists()


@pytest.mark.asyncio
async def test_delete_site_is_idempotent_when_nothing_to_delete(tmp_path):
    project = _make_project(tmp_path)

    await MkDocsGenerator().delete_site(project)  # no debe lanzar
