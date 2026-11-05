"""Tests de SiteGenerator (L-8, G10: zensical.toml + index.md + build del sitio con Zensical)."""

import importlib.util
import subprocess
import tomllib

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context import site_generator as site_generator_module
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.site_generator import SiteGenerator, SiteResult
from doc_organize.core.exceptions import DocOrganizeError, InvalidPathError, SiteBuildError
from doc_organize.core.models import Context, Domain, DomainDocument, Project


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _make_context(project: Project, domains: list[Domain]) -> Context:
    now = datetime.now(UTC).isoformat()
    return Context(project_name=project.name, domains=domains, created_at=now, updated_at=now)


def _document(stem: str, title: str, *, material_type: str | None = None, material_type_name: str | None = None) -> DomainDocument:
    return DomainDocument(
        source_path=f"/docs/{stem}.pdf",
        markdown_path=f"/out/{stem}.md",
        json_path=f"/out/{stem}.json",
        title=title,
        document_type="pdf",
        material_type=material_type,
        material_type_name=material_type_name,
        confidence=0.9,
    )


def _config(tmp_path) -> dict:
    return tomllib.loads((tmp_path / "zensical.toml").read_text(encoding="utf-8"))["project"]


def _fake_run(returncode: int = 0, stderr: str = "", calls: list | None = None):
    def run(*args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args[0], returncode=returncode, stdout="", stderr=stderr)

    return run


@pytest.fixture
def zensical_installed(monkeypatch) -> list:
    """Simula `zensical` instalado sin ejecutarlo: devuelve las llamadas a `subprocess.run`."""
    calls: list = []
    monkeypatch.setattr(SiteGenerator, "_zensical_command", staticmethod(lambda: ["zensical"]))
    monkeypatch.setattr(site_generator_module.subprocess, "run", _fake_run(calls=calls))
    return calls


# --- Configuración -------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_writes_valid_toml_with_nav_grouped_by_domain(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[_document("x", "Informe X")])])

    result = await SiteGenerator().generate(project, context, build=False)

    assert result == SiteResult(
        config_path=tmp_path / "zensical.toml", index_path=tmp_path / "organizado" / "index.md", site_dir=tmp_path / "site", site_built=False
    )
    config = _config(tmp_path)
    assert config["docs_dir"] == "organizado"
    assert config["site_dir"] == "site"
    assert config["nav"] == [{"Inicio": "index.md"}, {"Calidad": [{"Informe X": "calidad/pdf/x/x.md"}]}]


@pytest.mark.asyncio
async def test_generated_config_adds_no_javascript_plugins_nor_extensions(tmp_path):
    """L-8: sin JavaScript propio, `extra_javascript`, plugins ni extensiones Markdown distintas de las de Zensical."""
    project = _make_project(tmp_path)

    await SiteGenerator().generate(project, _make_context(project, []), build=False)

    config = _config(tmp_path)
    assert set(config) == {"site_name", "docs_dir", "site_dir", "nav", "theme"}
    assert config["theme"] == {"language": "es", "font": False}


@pytest.mark.asyncio
async def test_generate_groups_nav_by_material_type_when_taxonomy_manifest_used(tmp_path):
    project = _make_project(tmp_path)
    documents = [_document("a", "Norma A", material_type="normativa"), _document("b", "Proc B", material_type="procedimiento")]
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=documents)])
    context.taxonomy_manifest_used = True

    await SiteGenerator().generate(project, context, build=False)

    assert _config(tmp_path)["nav"][1] == {
        "Calidad": [
            {"Normativa": [{"Norma A": "calidad/normativa/a/a.md"}]},
            {"Procedimiento": [{"Proc B": "calidad/procedimiento/b/b.md"}]},
        ]
    }


@pytest.mark.asyncio
async def test_generate_nav_prefers_material_type_name_over_slug_derived_label(tmp_path):
    project = _make_project(tmp_path)
    document = _document("a", "Norma A", material_type="normativa", material_type_name="Normativa Vigente")
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])
    context.taxonomy_manifest_used = True

    await SiteGenerator().generate(project, context, build=False)

    assert _config(tmp_path)["nav"][1] == {"Calidad": [{"Normativa Vigente": [{"Norma A": "calidad/normativa/a/a.md"}]}]}


@pytest.mark.asyncio
async def test_titles_from_documents_are_escaped_in_toml(tmp_path):
    """Los títulos salen de documentos no confiables: barras, saltos y controles no rompen el TOML, y las comillas y
    `&` llegan escapados para el HTML (Zensical inserta las etiquetas del `nav` sin escapar)."""
    project = _make_project(tmp_path)
    title = "Tit 'uno' \\ dos\n]] = { x = 1 }\t\x00\x1f\x7f é 😀 & co"
    context = _make_context(project, [Domain(slug="calidad", name="Cal 'x'\n[project]", documents=[_document("x", title)])])

    await SiteGenerator().generate(project, context, build=False)

    expected_title = "Tit &#x27;uno&#x27; \\ dos\n]] = { x = 1 }\t\x00\x1f\x7f é 😀 &amp; co"
    assert _config(tmp_path)["nav"][1] == {"Cal &#x27;x&#x27;\n[project]": [{expected_title: "calidad/pdf/x/x.md"}]}


@pytest.mark.asyncio
async def test_html_in_labels_never_reaches_zensical_as_tags(tmp_path):
    """El tema mete el título en `<title>` con `striptags`, que deshace `&lt;`: `<`/`>` pasan a `＜`/`＞`."""
    project = Project(name="P</title><b>x</b>", root_path=str(tmp_path), created_at="x")
    document = _document("x", "</title><script>alert(1)</script>")
    context = _make_context(project, [Domain(slug="calidad", name="<svg onload=alert(2)>", documents=[document])])

    await SiteGenerator().generate(project, context, build=False)

    raw = (tmp_path / "zensical.toml").read_text(encoding="utf-8") + (tmp_path / "organizado" / "index.md").read_text(encoding="utf-8")
    assert "<" not in raw
    assert _config(tmp_path)["nav"][1] == {"＜svg onload=alert(2)＞": [{"＜/title＞＜script＞alert(1)＜/script＞": "calidad/pdf/x/x.md"}]}


@pytest.mark.asyncio
async def test_generate_writes_index_md_listing_domains_with_html_escaped(tmp_path):
    project = _make_project(tmp_path)
    context = _make_context(project, [Domain(slug="calidad", name="Calidad <script>alert(1)</script> & co")])

    await SiteGenerator().generate(project, context, build=False)

    index_content = (tmp_path / "organizado" / "index.md").read_text(encoding="utf-8")
    assert "Calidad ＜script＞alert(1)＜/script＞ &amp; co" in index_content
    assert "<script>" not in index_content


@pytest.mark.asyncio
async def test_generate_handles_empty_context_without_crashing(tmp_path):
    project = _make_project(tmp_path)

    await SiteGenerator().generate(project, _make_context(project, []), build=False)

    assert _config(tmp_path)["nav"] == [{"Inicio": "index.md"}]


@pytest.mark.asyncio
async def test_generate_removes_legacy_mkdocs_config(tmp_path):
    """Un contexto de antes de 0.13.0 (con `mkdocs.yml`) pasa a Zensical al regenerarlo."""
    project = _make_project(tmp_path)
    (tmp_path / "mkdocs.yml").write_text("site_name: viejo\n", encoding="utf-8")

    await SiteGenerator().generate(project, _make_context(project, []), build=False)

    assert not (tmp_path / "mkdocs.yml").exists()
    assert (tmp_path / "zensical.toml").is_file()


# --- site_dir --------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_site_dir_inside_project_is_written_relative(tmp_path, zensical_installed):
    project = _make_project(tmp_path)

    result = await SiteGenerator().generate(project, _make_context(project, []), site_dir=Path("publicado") / "web")

    assert result.site_dir == tmp_path / "publicado" / "web"
    assert result.site_built is True
    assert _config(tmp_path)["site_dir"] == "publicado/web"


@pytest.mark.asyncio
@pytest.mark.parametrize("site_dir", ["../fuera", ".", "organizado", "organizado/site", "Conversión", "domains/x", "duplicados", ".cache"])
async def test_invalid_site_dir_is_rejected_before_writing(tmp_path, site_dir):
    """Zensical vacía `site_dir` al construir: nunca la raíz, la carpeta reorganizada ni otra reservada."""
    project = _make_project(tmp_path)

    with pytest.raises(InvalidPathError):
        await SiteGenerator().generate(project, _make_context(project, []), site_dir=Path(site_dir), build=False)

    assert not (tmp_path / "zensical.toml").exists()


@pytest.mark.asyncio
async def test_absolute_site_dir_outside_project_is_rejected(tmp_path):
    project_root = tmp_path / "proyecto"
    project_root.mkdir()
    project = _make_project(project_root)

    with pytest.raises(InvalidPathError):
        await SiteGenerator().generate(project, _make_context(project, []), site_dir=tmp_path / "otro", build=False)


# --- Build -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_runs_zensical_on_the_generated_config(tmp_path, zensical_installed):
    project = _make_project(tmp_path)

    result = await SiteGenerator().generate(project, _make_context(project, []), timeout=30)

    assert result.site_built is True
    (args, kwargs) = zensical_installed[0]
    assert args[0] == ["zensical", "build", "-f", str(tmp_path / "zensical.toml")]
    assert kwargs["timeout"] == 30


@pytest.mark.asyncio
async def test_missing_zensical_raises_site_build_error_after_writing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(SiteGenerator, "_zensical_command", staticmethod(lambda: None))
    project = _make_project(tmp_path)

    with pytest.raises(SiteBuildError, match="zensical no está instalado"):
        await SiteGenerator().generate(project, _make_context(project, []))

    assert (tmp_path / "zensical.toml").is_file()
    assert not (tmp_path / "site").exists()


@pytest.mark.asyncio
async def test_failed_build_raises_site_build_error_with_output(tmp_path, monkeypatch):
    monkeypatch.setattr(SiteGenerator, "_zensical_command", staticmethod(lambda: ["zensical"]))
    monkeypatch.setattr(site_generator_module.subprocess, "run", _fake_run(returncode=1, stderr="Error: boom"))
    project = _make_project(tmp_path)

    with pytest.raises(SiteBuildError, match="boom"):
        await SiteGenerator().generate(project, _make_context(project, []))


@pytest.mark.asyncio
async def test_build_timeout_raises_site_build_error(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(SiteGenerator, "_zensical_command", staticmethod(lambda: ["zensical"]))
    monkeypatch.setattr(site_generator_module.subprocess, "run", timeout)
    project = _make_project(tmp_path)

    with pytest.raises(SiteBuildError, match="tiempo máximo"):
        await SiteGenerator().generate(project, _make_context(project, []), timeout=0.5)


def test_site_build_error_is_a_doc_organize_error():
    assert issubclass(SiteBuildError, DocOrganizeError)


def test_zensical_command_prefers_the_current_environment(monkeypatch):
    monkeypatch.setattr(site_generator_module.importlib.util, "find_spec", lambda name: object())

    command = SiteGenerator._zensical_command()

    assert command is not None
    assert command[1:] == ["-m", "zensical"]


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(importlib.util.find_spec("zensical") is None, reason="Requiere el extra 'site' (zensical)")
async def test_real_build_produces_site_and_keeps_embedded_html_as_zensical_does(tmp_path):
    """Build real con Zensical. Documenta el comportamiento por defecto con Markdown no confiable: el HTML
    incrustado llega tal cual al sitio (ver `SiteGenerator` y docs/functional/context.md); quien sirve el sitio debe
    aislarlo. La configuración generada no añade ningún `<script>` propio."""
    project = _make_project(tmp_path)
    for name in ("informe.pdf", "informe.json"):
        (tmp_path / name).write_bytes(b"{}")
    (tmp_path / "informe.md").write_text("# Informe\n\n<script>alert('x')</script>\n", encoding="utf-8")
    document = DomainDocument(
        source_path=str(tmp_path / "informe.pdf"),
        markdown_path=str(tmp_path / "informe.md"),
        json_path=str(tmp_path / "informe.json"),
        title="</title><script>alert('titulo')</script>",
        document_type="pdf",
        confidence=0.9,
    )
    context = _make_context(project, [Domain(slug="calidad", name="Calidad", documents=[document])])
    await Reorganizer().reorganize(project, context)

    result = await SiteGenerator().generate(project, context, timeout=120)

    assert result.site_built is True
    page = (tmp_path / "site" / "calidad" / "pdf" / "informe" / "informe" / "index.html").read_text(encoding="utf-8")
    assert "<script>alert('x')</script>" in page  # HTML del propio Markdown: Zensical lo deja pasar
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(" not in index  # el título (nav) no llega como HTML a ninguna página
    assert "<script>alert('titulo')" not in page


# --- Borrado ---------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_site_removes_config_legacy_config_site_and_cache(tmp_path):
    project = _make_project(tmp_path)
    generator = SiteGenerator()
    await generator.generate(project, _make_context(project, []), build=False)
    (tmp_path / "mkdocs.yml").write_text("site_name: viejo\n", encoding="utf-8")
    for directory in ("site", ".cache"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "x").write_text("x", encoding="utf-8")

    await generator.delete_site(project)

    for name in ("zensical.toml", "mkdocs.yml", "site", ".cache"):
        assert not (tmp_path / name).exists()
    assert (tmp_path / "organizado" / "index.md").exists()  # la carpeta reorganizada no es suya


@pytest.mark.asyncio
async def test_delete_site_is_idempotent_when_nothing_to_delete(tmp_path):
    await SiteGenerator().delete_site(_make_project(tmp_path))  # no debe lanzar


@pytest.mark.asyncio
async def test_delete_site_with_custom_site_dir(tmp_path):
    project = _make_project(tmp_path)
    (tmp_path / "publicado").mkdir()
    (tmp_path / "publicado" / "index.html").write_text("x", encoding="utf-8")

    await SiteGenerator().delete_site(project, site_dir=Path("publicado"))

    assert not (tmp_path / "publicado").exists()


# --- Retirados en 1.0.0 (alias de antes de 0.13.0) -------------------------------------------------------------------


def test_mkdocs_generator_no_longer_exists():
    import doc_organize
    import doc_organize.context

    assert "MkDocsGenerator" not in doc_organize.__all__
    assert not hasattr(doc_organize.context, "MkDocsGenerator")
    with pytest.raises(ImportError):
        import doc_organize.context.mkdocs_generator


def test_legacy_context_json_mkdocs_keys_are_still_read_but_properties_are_gone():
    legacy = Context.model_validate({"project_name": "x", "created_at": "a", "updated_at": "b", "mkdocs_generated": True, "mkdocs_site_built": True})

    assert (legacy.site_generated, legacy.site_built) == (True, True)
    assert "mkdocs_generated" not in legacy.model_dump()
    assert not hasattr(legacy, "mkdocs_generated")
    assert not hasattr(legacy, "mkdocs_site_built")


@pytest.mark.asyncio
async def test_generate_rejects_a_linked_output_folder_before_writing(tmp_path):
    secret = tmp_path / "fuera"
    secret.mkdir()
    (tmp_path / "proyecto").mkdir()
    try:
        (tmp_path / "proyecto" / "organizado").symlink_to(secret, target_is_directory=True)
    except OSError:
        import _winapi  # Windows sin privilegio de symlink: una unión

        _winapi.CreateJunction(str(secret), str(tmp_path / "proyecto" / "organizado"))
    project = _make_project(tmp_path / "proyecto")

    with pytest.raises(InvalidPathError):
        await SiteGenerator().generate(project, _make_context(project, []), build=False)

    assert list(secret.iterdir()) == []
    assert not (tmp_path / "proyecto" / "zensical.toml").exists()
