"""Tests de web/ai_settings_config.py (spec de familias de IA + resolución store/entorno)."""

import pytest

from doc_organize.auth import InstanceSecretsStore
from doc_organize.web.ai_settings_config import get_family, is_family_configured, resolve_field_value


def test_get_family_returns_none_for_unknown_key() -> None:
    assert get_family("no-existe") is None


def test_get_family_returns_all_five_known_families() -> None:
    keys = {
        "litellm_classification",
        "litellm_taxonomy_classification",
        "litellm_taxonomy_manifest_draft",
        "litellm_usage",
        "github_copilot_usage",
    }
    for key in keys:
        assert get_family(key) is not None
        assert get_family(key).key == key


@pytest.mark.asyncio
async def test_resolve_field_value_treats_empty_stored_string_as_unset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_BASE_URL", "https://env.example.com")
    family = get_family("litellm_usage")
    base_url_field = next(f for f in family.fields if f.name == "base_url")

    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set(base_url_field.env_var_name.lower(), "", is_secret=False)

        value = await resolve_field_value(base_url_field, store)

    assert value == "https://env.example.com"


@pytest.mark.asyncio
async def test_is_family_configured_false_when_required_field_stored_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_VIRTUAL_KEY", raising=False)
    family = get_family("litellm_usage")
    base_url_field = next(f for f in family.fields if f.name == "base_url")

    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set(base_url_field.env_var_name.lower(), "", is_secret=False)

        configured = await is_family_configured(family, store)

    assert configured is False
