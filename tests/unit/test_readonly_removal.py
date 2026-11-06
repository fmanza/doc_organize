"""Borrado de carpetas con ficheros de solo lectura (hotfix 1.1.1).

`shutil.copy2` conserva el atributo de solo lectura de Windows, así que copiar un original de solo lectura (carpeta de
red, CD, descarga) dejaba en el proyecto ficheros que `shutil.rmtree` no podía borrar: `delete_project` fallaba con
`WinError 5` a mitad de borrado y el proyecto quedaba registrado y medio vacío. En POSIX estos tests pasan igual (el
atributo no existe), lo que comprueba que el comportamiento no cambia allí.
"""

import errno
import os
import stat
import subprocess
import sys

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context.reorganizer import Reorganizer
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.projects.project_history_cleaner import ProjectHistoryCleaner
from doc_organize.projects.project_registry import ProjectRegistry
from doc_organize.utils import path_utils
from doc_organize.utils.path_utils import remove_tree


def _readonly_file(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IREAD)
    return path


def _is_readonly(path: Path) -> bool:
    return not os.access(path, os.W_OK)


def test_remove_tree_deletes_readonly_files_and_folders(tmp_path: Path) -> None:
    folder = tmp_path / "proyecto"
    _readonly_file(folder / "duplicados" / "copia.pdf")
    _readonly_file(folder / "raiz.txt")
    if sys.platform == "win32":  # en POSIX una carpeta sin escritura sí impide borrar su contenido, como antes
        os.chmod(folder / "duplicados", stat.S_IREAD | stat.S_IEXEC)

    remove_tree(folder)

    assert not folder.exists()


def test_remove_tree_reraises_permission_errors_that_are_not_the_readonly_attribute(tmp_path: Path) -> None:
    writable = tmp_path / "normal.txt"
    writable.write_text("x", encoding="utf-8")
    error = PermissionError(errno.EACCES, "bloqueado por otro proceso", str(writable))

    with pytest.raises(PermissionError, match="bloqueado"):
        path_utils._clear_readonly_and_retry(os.unlink, str(writable), error)
    with pytest.raises(OSError, match="otro error"):
        path_utils._clear_readonly_and_retry(os.unlink, str(writable), OSError("otro error"))
    assert writable.exists()


def test_remove_tree_ignore_errors_swallows_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(path: object, **_kwargs: object) -> None:
        raise OSError("fallo simulado")

    monkeypatch.setattr(path_utils.shutil, "rmtree", _boom)

    remove_tree(tmp_path / "carpeta", ignore_errors=True)
    with pytest.raises(OSError, match="fallo simulado"):
        remove_tree(tmp_path / "carpeta")


@pytest.mark.skipif(sys.platform != "win32", reason="uniones de Windows")
def test_remove_tree_does_not_touch_readonly_files_behind_a_junction(tmp_path: Path) -> None:
    outside = tmp_path / "fuera"
    original = _readonly_file(outside / "original.pdf")
    folder = tmp_path / "proyecto"
    _readonly_file(folder / "copia.pdf")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(folder / "salida"), str(outside)], check=True, capture_output=True)

    remove_tree(folder)

    assert not folder.exists()
    assert original.read_text(encoding="utf-8") == "x"
    assert _is_readonly(original)


@pytest.mark.asyncio
async def test_delete_project_removes_project_with_readonly_copies(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Solo Lectura", base)
        root = Path(project.root_path)
        _readonly_file(root / "Duplicados" / "factura.pdf")
        _readonly_file(root / "Conversión" / "factura.pdf")

        await registry.delete_project("Solo Lectura")

        assert await registry.list_projects() == []
    assert not root.exists()


@pytest.mark.asyncio
async def test_move_project_root_across_volumes_removes_readonly_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    destination = tmp_path / "otro-volumen"
    destination.mkdir()

    def _cross_device(source: object, target: object) -> None:
        raise OSError(errno.EXDEV, "otro volumen")

    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Movil", base)
        old_root = Path(project.root_path)
        _readonly_file(old_root / "Duplicados" / "factura.pdf", "contenido")
        monkeypatch.setattr(path_utils.os, "rename", _cross_device)

        moved = await registry.move_project_root("Movil", destination)

    new_root = Path(moved.root_path)
    assert not old_root.exists()
    assert (new_root / "Duplicados" / "factura.pdf").read_text(encoding="utf-8") == "contenido"
    assert (new_root / "project.json").is_file()


@pytest.mark.asyncio
async def test_history_cleaner_clears_readonly_copies(tmp_path: Path) -> None:
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    _readonly_file(tmp_path / "Duplicados" / "factura.pdf")

    await ProjectHistoryCleaner().clear(project)

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["project.json"]


@pytest.mark.asyncio
async def test_reorganizer_rebuilds_and_deletes_output_with_readonly_originals(tmp_path: Path) -> None:
    project = Project(name="Demo", root_path=str(tmp_path / "proyecto"), created_at=datetime.now(UTC).isoformat())
    Path(project.root_path).mkdir()
    source = _readonly_file(tmp_path / "originales" / "informe.pdf")
    markdown = tmp_path / "informe.md"
    markdown.write_text("# Informe", encoding="utf-8")
    json_file = tmp_path / "informe.json"
    json_file.write_text("{}", encoding="utf-8")
    document = DomainDocument(
        source_path=str(source),
        markdown_path=str(markdown),
        json_path=str(json_file),
        title="Informe",
        document_type="pdf",
        confidence=0.9,
    )
    now = datetime.now(UTC).isoformat()
    context = Context(
        project_name=project.name, domains=[Domain(slug="calidad", name="Calidad", documents=[document])], created_at=now, updated_at=now
    )
    reorganizer = Reorganizer()

    output_root = await reorganizer.reorganize(project, context)
    output_root = await reorganizer.reorganize(project, context)  # reconstruir borra la carpeta del dominio anterior
    assert any(_is_readonly(path) for path in output_root.rglob("informe.pdf"))

    await reorganizer.delete_output(project, context)

    assert not output_root.exists()
    assert source.exists()
