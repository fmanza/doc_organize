"""Arquitectura de la librería pura (1.0.0, L-11): sin web integrada ni `auth/`, que viven en doc_organize_web."""

import ast
import importlib.util
import tomllib

from pathlib import Path

import pytest

import doc_organize

SRC = Path(doc_organize.__file__).parent
PYPROJECT = SRC.parent.parent / "pyproject.toml"

#: Paquetes de servidor web/plantillas que la librería no puede volver a importar.
FORBIDDEN_THIRD_PARTY = ("fastapi", "starlette", "uvicorn", "jinja2", "multipart", "python_multipart")
#: Subpaquetes retirados en 1.0.0.
REMOVED_SUBPACKAGES = ("doc_organize.web", "doc_organize.auth")


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def test_library_does_not_import_web_frameworks() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(m for m in _imports(path) if _matches(m, FORBIDDEN_THIRD_PARTY))
        for path in SRC.rglob("*.py")
        if any(_matches(m, FORBIDDEN_THIRD_PARTY) for m in _imports(path))
    }

    assert offenders == {}


def test_library_does_not_import_removed_subpackages() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(m for m in _imports(path) if _matches(m, REMOVED_SUBPACKAGES))
        for path in SRC.rglob("*.py")
        if any(_matches(m, REMOVED_SUBPACKAGES) for m in _imports(path))
    }

    assert offenders == {}


@pytest.mark.parametrize("subpackage", REMOVED_SUBPACKAGES)
def test_removed_subpackages_do_not_exist(subpackage: str) -> None:
    assert not (SRC / subpackage.rsplit(".", 1)[1]).exists()
    assert importlib.util.find_spec(subpackage) is None


def test_public_api_exports_nothing_from_web_auth_or_tenants() -> None:
    names = {name.lower() for name in doc_organize.__all__}
    modules = set(doc_organize._EXPORTS.values())

    assert not any(_matches(module, REMOVED_SUBPACKAGES) for module in modules)
    assert not {name for name in names if "tenant" in name or "secret" in name or name in {"user", "role", "session"}}


@pytest.mark.skipif(not PYPROJECT.is_file(), reason="solo desde el árbol de fuentes")
def test_pyproject_declares_no_web_dependencies() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    extras: dict[str, list[str]] = project.get("optional-dependencies", {})
    requirements = [*project.get("dependencies", []), *(req for reqs in extras.values() for req in reqs)]

    assert "web" not in extras
    assert not [req for req in requirements if _matches(req.split(">")[0].split("[")[0].strip().replace("-", "_"), FORBIDDEN_THIRD_PARTY)]
