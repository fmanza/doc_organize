"""Arquitectura de `ai/` (L-3, G3): los clientes de IA no dependen de `auth/` ni de `web/`."""

import ast

from pathlib import Path

import doc_organize.ai as ai_package

AI_DIR = Path(ai_package.__file__).parent
FORBIDDEN = ("doc_organize.auth", "doc_organize.web")


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_ai_does_not_import_auth_or_web() -> None:
    offenders = {
        path.name: sorted(m for m in _imports(path) if m.startswith(FORBIDDEN))
        for path in AI_DIR.glob("*.py")
        if any(m.startswith(FORBIDDEN) for m in _imports(path))
    }

    assert offenders == {}
