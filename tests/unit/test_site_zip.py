"""`write_site_zip` (M9, F3): ZIP reproducible del sitio sin conexión, con servidor local y guía."""

import functools
import hashlib
import importlib.util
import io
import socketserver
import threading
import urllib.request
import zipfile

from pathlib import Path

import pytest

from doc_organize.context.offline_site import SITE_ZIP_FOLDER, write_site_zip
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.exceptions import InvalidPathError, OfflineSiteError, OperationCancelledError
from doc_organize.core.progress import CancelToken, ProgressEvent
from tests.unit.test_site_offline import _reorganized


def _site(root: Path) -> Path:
    pages = {
        "index.html": '<a href="b/pagina.html">b</a><script src="assets/x.js"></script>',
        "b/pagina.html": '<a href="../index.html">inicio</a>',
        "assets/x.js": "var x = 1;",
        "search.js": "var index = {};",
    }
    for relative, text in pages.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")
    return root


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_zip_is_reproducible_and_complete(tmp_path) -> None:
    site = _site(tmp_path / "site")
    events: list[ProgressEvent] = []

    first = write_site_zip(tmp_path / "a.zip", site, project_name="Demo $x", on_progress=events.append)
    (site / "b" / "pagina.html").touch()  # otra fecha de modificación: no cambia el ZIP
    second = write_site_zip(tmp_path / "b.zip", site, project_name="Demo $x")
    buffer = io.BytesIO()
    in_memory = write_site_zip(buffer, site, project_name="Demo $x")

    assert first.sha256 == second.sha256 == in_memory.sha256 == _sha(tmp_path / "a.zip") == hashlib.sha256(buffer.getvalue()).hexdigest()
    assert first.file_count == 6 and first.zip_size_bytes == (tmp_path / "a.zip").stat().st_size
    with zipfile.ZipFile(tmp_path / "a.zip") as archive:
        names = archive.namelist()
        assert names == [
            "VER_SITIO.md",
            "start_server.py",
            f"{SITE_ZIP_FOLDER}/assets/x.js",
            f"{SITE_ZIP_FOLDER}/b/pagina.html",
            f"{SITE_ZIP_FOLDER}/index.html",
            f"{SITE_ZIP_FOLDER}/search.js",
        ]
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert "**Demo $x**" in archive.read("VER_SITIO.md").decode("utf-8")
        assert b"127.0.0.1" in archive.read("start_server.py")
    assert events[0].phase == "started" and events[-1].phase == "done" and events[-1].processed == 6
    assert write_site_zip(tmp_path / "c.zip", site, project_name="Otro").sha256 != first.sha256  # la guía lleva el nombre


def test_a_site_that_fails_the_check_is_rejected(tmp_path) -> None:
    site = _site(tmp_path / "site")
    (site / "index.html").write_text('<script src="https://unpkg.com/x.js"></script>', encoding="utf-8")

    with pytest.raises(OfflineSiteError) as error:
        write_site_zip(tmp_path / "sitio.zip", site)

    assert any("unpkg.com" in problem for problem in error.value.problems) and not (tmp_path / "sitio.zip").exists()


def test_cancel_removes_the_partial_zip_and_destination_inside_the_site_is_refused(tmp_path) -> None:
    site = _site(tmp_path / "site")
    token = CancelToken()
    token.cancel()

    with pytest.raises(OperationCancelledError):
        write_site_zip(tmp_path / "sitio.zip", site, cancel_token=token)
    assert not (tmp_path / "sitio.zip").exists()
    with pytest.raises(InvalidPathError):
        write_site_zip(site / "sitio.zip", site)


def test_start_server_serves_the_site_only_on_localhost(tmp_path) -> None:
    write_site_zip(tmp_path / "sitio.zip", _site(tmp_path / "site"))
    with zipfile.ZipFile(tmp_path / "sitio.zip") as archive:
        archive.extractall(tmp_path / "entregado")
    spec = importlib.util.spec_from_file_location("start_server_entregado", tmp_path / "entregado" / "start_server.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    assert module.SITE == (tmp_path / "entregado" / "sitio").resolve()
    handler = functools.partial(module._Handler, directory=str(module.SITE))
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/b/pagina.html", timeout=10) as response:
                assert b"inicio" in response.read()
        finally:
            server.shutdown()
    source = (tmp_path / "entregado" / "start_server.py").read_text(encoding="utf-8")
    assert '("127.0.0.1", 0)' in source and "0.0.0.0" not in source


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(importlib.util.find_spec("zensical") is None, reason="Requiere el extra 'site' (zensical)")
async def test_two_builds_of_the_same_context_give_the_same_zip(tmp_path) -> None:
    """Puerta de M9: mismo `site/` → mismo SHA-256, también entre dos construcciones del mismo contexto."""
    shas = []
    for run in ("uno", "dos"):
        root = tmp_path / run
        root.mkdir()
        project, context = await _reorganized(root)
        result = await SiteGenerator().generate(project, context, offline=True, timeout=300)
        shas.append(write_site_zip(tmp_path / f"{run}.zip", result.site_dir, project_name="Demo").sha256)

    assert shas[0] == shas[1]
