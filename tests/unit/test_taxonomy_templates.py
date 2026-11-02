"""Plantillas de taxonomía como texto (L-8c, G29): parsear, renderizar y plantillas empaquetadas sin carpeta de usuario."""

import random
import subprocess
import sys

from pathlib import Path

import pytest

import doc_organize

from doc_organize.context import TaxonomyTemplateRegistry, taxonomy_templates
from doc_organize.context.taxonomy_templates import list_builtin_templates, load_builtin_template, parse_taxonomy_template, render_taxonomy_template
from doc_organize.core.exceptions import TaxonomyTemplateError
from doc_organize.core.models import TaxonomyCatalogEntry, TaxonomyManifest

BUILTIN_DIR = Path(taxonomy_templates.__file__).parent / "taxonomy_templates_builtin"


def _manifest(**kwargs) -> TaxonomyManifest:
    return TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad", description="Gestión", keywords=["iso 9001"])],
        material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento")],
        **kwargs,
    )


def test_public_names_are_exported() -> None:
    for name in ("parse_taxonomy_template", "render_taxonomy_template", "list_builtin_templates", "load_builtin_template"):
        assert getattr(doc_organize, name) is getattr(taxonomy_templates, name)


def test_parse_ignores_the_body() -> None:
    text = "---\ndomains:\n  - slug: a\n    name: A\nmaterial_types:\n  - slug: b\n    name: B\n---\n# Cuerpo\n\n---\nmás\n"

    manifest = parse_taxonomy_template(text)

    assert [entry.slug for entry in manifest.domains] == ["a"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("domains: []\n", "debe empezar con el delimitador"),
        ("---\ndomains: []\n", "no cierra el front matter"),
        ("---\ndomains: [\n---\n", "no es válido"),
        ("---\n- a\n---\n", "debe ser un mapeo YAML"),
        ("---\ndomains: []\nmaterial_types: []\n---\n", "no cumple el schema"),
        ("", "debe empezar con el delimitador"),
    ],
)
def test_parse_raises_the_same_errors_as_loading_a_template_file(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(TaxonomyTemplateError, match=message) as from_text:
        parse_taxonomy_template(text, source="mi-plantilla")
    (tmp_path / "rota.md").write_text(text, encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path)

    import asyncio

    with pytest.raises(TaxonomyTemplateError) as from_file:
        asyncio.run(registry.load_template("rota"))

    assert "'mi-plantilla'" in str(from_text.value)
    assert str(from_file.value) == str(from_text.value).replace("mi-plantilla", str(tmp_path / "rota.md"))


@pytest.mark.parametrize(
    "manifest",
    [
        _manifest(),
        _manifest(title="Calidad", description="Plantilla de ejemplo"),
        _manifest(title="", description=""),
        _manifest(title="a\n---\nb", description="línea 1\r\nlínea 2 tres\x85cuatro"),
        _manifest(title="yes", description="null"),
    ],
)
def test_render_then_parse_is_identity(manifest: TaxonomyManifest) -> None:
    assert parse_taxonomy_template(render_taxonomy_template(manifest)) == manifest
    assert parse_taxonomy_template(render_taxonomy_template(manifest, "# Notas\n\n---\n")) == manifest


def test_render_then_parse_is_identity_for_random_texts() -> None:
    pieces = ["a", "-", "---", "\n", "\r", "\r\n", " ", " ", "\x85", "\x0b", "\x0c", "\x1c", "\t", " ", "'", '"', "#", ":",
              "é", "...", "\x00", "﻿", "yes", "null", "1.0", "~", "&", "*", "!", "%", "@", "`", "|", ">", "{", "}", "[", "]"]  # fmt: skip
    rng = random.Random(8)

    def text() -> str:
        return "".join(rng.choice(pieces) for _ in range(rng.randint(1, 10)))

    for _ in range(500):
        manifest = TaxonomyManifest(
            title=rng.choice([None, "", text()]),
            description=rng.choice([None, "", text()]),
            domains=[TaxonomyCatalogEntry(slug=text(), name=text(), description=rng.choice([None, text()]), keywords=[text()])],
            material_types=[TaxonomyCatalogEntry(slug=text(), name=text())],
        )
        assert parse_taxonomy_template(render_taxonomy_template(manifest, text())) == manifest


def test_render_body_follows_the_front_matter() -> None:
    text = render_taxonomy_template(_manifest(), "# Notas\n")

    assert text.startswith("---\n")
    assert text.endswith("---\n\n# Notas\n")


def test_builtin_templates_are_listed_and_loaded_from_the_package() -> None:
    names = [summary.name for summary in list_builtin_templates()]

    assert names == sorted(path.stem for path in BUILTIN_DIR.glob("*.md"))
    for name in names:
        assert load_builtin_template(name).domains


@pytest.mark.parametrize("name", ["../calidad", "Calidad", "no-existe", ""])
def test_load_builtin_template_rejects_bad_or_unknown_names(name: str) -> None:
    with pytest.raises(TaxonomyTemplateError):
        load_builtin_template(name)


def test_builtin_templates_do_not_need_a_home_directory() -> None:
    """Las plantillas empaquetadas no usan la carpeta de usuario: con `Path.home()` roto, siguen funcionando, y el
    módulo de plantillas como texto se importa sin llamarlo."""
    code = (
        "import pathlib\n"
        "def fail(*args, **kwargs): raise RuntimeError('Path.home()')\n"
        "from doc_organize.context import list_builtin_templates, load_builtin_template\n"
        "pathlib.Path.home = classmethod(fail)\n"
        "import importlib, doc_organize.context.taxonomy_templates as module\n"
        "importlib.reload(module)\n"
        "print(len(module.list_builtin_templates()), bool(module.load_builtin_template('calidad').domains))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[1] == "True"


def test_registry_module_does_not_call_path_home_on_import() -> None:
    code = (
        "import pathlib, importlib\n"
        "import doc_organize.context.taxonomy_template_registry as module\n"
        "def fail(*args, **kwargs): raise RuntimeError('Path.home()')\n"
        "pathlib.Path.home = classmethod(fail)\n"
        "importlib.reload(module)\n"
        "print(module.TaxonomyTemplateRegistry('/tmp/x').templates_dir.name)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_registry_saves_with_render_and_reloads_identical(tmp_path: Path) -> None:
    registry = TaxonomyTemplateRegistry(tmp_path)
    manifest = _manifest(title="T", description="línea\n---\notra")

    await registry.save_template("mia", manifest)

    assert (tmp_path / "mia.md").read_text(encoding="utf-8") == render_taxonomy_template(manifest)
    assert await registry.load_template("mia") == manifest


@pytest.mark.asyncio
async def test_registry_delete_rejects_names_that_are_not_slugs(tmp_path: Path) -> None:
    victim = tmp_path / "fuera.md"
    victim.write_text("no borrar", encoding="utf-8")
    registry = TaxonomyTemplateRegistry(tmp_path / "plantillas")

    with pytest.raises(TaxonomyTemplateError, match="no es un nombre de plantilla válido"):
        await registry.delete_template("../fuera")

    assert victim.exists()
