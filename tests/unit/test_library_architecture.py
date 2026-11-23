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


# --- Jerarquía de dependencias (regla #6 de architecture.instructions.md) --------------------------------------------

#: Nivel de cada paquete (o módulo suelto) de primer nivel de `doc_organize`.
LEVELS: dict[str, int] = {
    "core": 1,
    "utils": 1,
    "security": 1,
    "validators": 2,
    "scanner": 2,
    "converter": 2,
    "dedup": 2,
    "cache": 2,
    "projects": 2,
    "ai": 2,
    "scan": 3,
    "context": 3,
    "export": 3,
    "diagnostics": 3,
    "main": 3,
    "__main__": 3,
    "__init__": 3,
}

#: Dependencias que la regla #6 no permitiría y se aceptan, cada una con su motivo (paquete que importa, importado).
#: Cualquier otra horizontal o hacia arriba hace fallar el test.
ALLOWED_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("utils", "core"): "core/ es la base del Nivel 1: utils/ usa sus constantes, modelos y excepciones",
    ("projects", "validators"): "ProjectRegistry valida el nombre con ProjectValidator",
    ("converter", "projects"): "projects/layout.py es el contrato de rutas de salida (resolve_output_paths)",
    ("dedup", "projects"): "projects/layout.py: carpeta de conversiones de los duplicados",
    ("dedup", "ai"): "duplicados por contenido (2.2.0): embeddings de la tarea dedup",
    ("dedup", "context"): "exclude_from_context (2.2.0), import diferido; se moverá a context/ en 3.0",
    ("ai", "context"): "ai/excerpt.py, solo bajo TYPE_CHECKING (tipo ConversionDocument)",
    ("export", "context"): "export/ exporta el contexto; context/ nunca importa export/",
}


def _package(path: Path) -> str:
    relative = path.relative_to(SRC)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def test_dependencies_follow_the_level_hierarchy() -> None:
    """Las dependencias van solo hacia abajo (regla #6), salvo `ALLOWED_EXCEPTIONS`; cuenta también los imports
    diferidos y los de `TYPE_CHECKING`."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in SRC.rglob("*.py"):
        source = _package(path)
        for module in _imports(path):
            if not module.startswith("doc_organize."):
                continue
            target = module.split(".")[1]
            if target == source or target not in LEVELS:
                continue
            if LEVELS[target] >= LEVELS[source] and source not in {"__init__", "main", "__main__"}:
                found.setdefault((source, target), []).append(str(path.relative_to(SRC)))
    unexpected = {pair: files for pair, files in found.items() if pair not in ALLOWED_EXCEPTIONS}
    assert unexpected == {}
    assert sorted(set(ALLOWED_EXCEPTIONS) - set(found)) == [], "Excepción que ya no hace falta: quítala de la lista"


def test_every_top_level_package_has_a_level() -> None:
    packages = {_package(path) for path in SRC.rglob("*.py")}
    assert sorted(packages - set(LEVELS)) == []
