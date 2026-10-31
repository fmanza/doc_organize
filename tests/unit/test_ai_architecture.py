"""Arquitectura de `ai/` (L-3, G3): los clientes de IA no dependen de `auth/` ni de `web/`."""

import ast

from pathlib import Path

import pytest

import doc_organize.ai as ai_package

from doc_organize.ai.domain_classification_client import litellm_classification_config_from_store_or_env

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


class _FakeStore:
    """Cualquier objeto con `async get(clave)` sirve (no hace falta `InstanceSecretsStore`)."""

    async def get(self, key: str) -> str | None:
        return {"doc_organize_litellm_classification_base_url": "https://litellm.example.internal"}.get(key)


@pytest.mark.asyncio
async def test_store_config_accepts_any_reader_and_is_deprecated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-prueba")

    with pytest.warns(DeprecationWarning, match="1.0.0"):
        config = await litellm_classification_config_from_store_or_env(_FakeStore())

    assert config.base_url == "https://litellm.example.internal"
