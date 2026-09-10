"""Tests de las rutas web del panel de configuración IA (/admin/configuracion-ia)."""

import httpx
import pytest

from doc_organize.web import create_app

_VALID_KEY = "zJx3nB2v9mQY9y3ZbG8cC1eR6tK0pL4sD7fH5wA2iU8="


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


@pytest.mark.asyncio
async def test_ai_settings_page_renders(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.get("/admin/configuracion-ia")

    assert response.status_code == 200
    assert "Configuración IA" in response.text


@pytest.mark.asyncio
async def test_get_ai_settings_lists_all_five_families(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.get("/api/admin/ai-settings")

    assert response.status_code == 200
    data = response.json()
    assert {family["key"] for family in data["families"]} == {
        "litellm_classification",
        "litellm_taxonomy_classification",
        "litellm_taxonomy_manifest_draft",
        "litellm_usage",
        "github_copilot_usage",
    }
    assert all(family["configured"] is False for family in data["families"])


@pytest.mark.asyncio
async def test_get_ai_settings_reports_encryption_status(tmp_path, monkeypatch) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")
    monkeypatch.delenv("DOC_ORGANIZE_SECRETS_KEY", raising=False)

    async with _client(app) as client:
        response = await client.get("/api/admin/ai-settings")
    assert response.json()["encryption_configured"] is False

    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    async with _client(app) as client:
        response = await client.get("/api/admin/ai-settings")
    assert response.json()["encryption_configured"] is True


@pytest.mark.asyncio
async def test_put_ai_settings_persists_non_secret_field(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"base_url": "https://litellm.example.com"}})
    assert response.status_code == 200
    family = response.json()
    base_url_field = next(f for f in family["fields"] if f["name"] == "base_url")
    assert base_url_field["value"] == "https://litellm.example.com"
    assert base_url_field["configured_via"] == "store"


@pytest.mark.asyncio
async def test_put_ai_settings_secret_field_never_echoes_the_value_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"virtual_key": "sk-abcd1234"}})
    assert response.status_code == 200
    field = next(f for f in response.json()["fields"] if f["name"] == "virtual_key")
    assert field["value"] is None
    assert field["masked_hint"] == "...1234"


@pytest.mark.asyncio
async def test_put_ai_settings_saving_a_secret_without_encryption_key_returns_400(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_SECRETS_KEY", raising=False)
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"virtual_key": "sk-abcd1234"}})

    assert response.status_code == 400
    assert "DOC_ORGANIZE_SECRETS_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_put_ai_settings_null_value_clears_a_stored_override(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")
    async with _client(app) as client:
        await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"base_url": "https://litellm.example.com"}})

        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"base_url": None}})

    field = next(f for f in response.json()["fields"] if f["name"] == "base_url")
    assert field["configured_via"] == "none"


@pytest.mark.asyncio
async def test_put_ai_settings_empty_string_clears_like_null(tmp_path, monkeypatch) -> None:
    """Guardar una cadena vacía nunca debe dejar el campo como "guardado" -- debe
    comportarse exactamente igual que enviar `null` (AUDIT_CODE, sesión 2026-09-11:
    antes una cadena vacía SÍ quedaba persistida, y el panel la mostraba como
    "guardado" mientras que la resolución real para clasificar caía al entorno)."""
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_BASE_URL", "https://env.example.com")
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"base_url": "https://store.example.com"}})

        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"base_url": ""}})

    field = next(f for f in response.json()["fields"] if f["name"] == "base_url")
    assert field["configured_via"] == "env"
    assert field["value"] == "https://env.example.com"


@pytest.mark.asyncio
async def test_masked_hint_shows_generic_marker_for_short_secrets(tmp_path, monkeypatch) -> None:
    """Un secreto de 4 caracteres o menos nunca debe aparecer completo bajo un hint
    que se presenta como "enmascarado" (AUDIT_CODE, sesión 2026-09-11)."""
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"virtual_key": "ab"}})

    field = next(f for f in response.json()["fields"] if f["name"] == "virtual_key")
    assert field["masked_hint"] == "***"
    assert "ab" not in field["masked_hint"]


@pytest.mark.asyncio
async def test_masked_hint_still_shows_suffix_for_normal_length_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"virtual_key": "sk-abcd1234"}})

    field = next(f for f in response.json()["fields"] if f["name"] == "virtual_key")
    assert field["masked_hint"] == "...1234"


@pytest.mark.asyncio
async def test_put_ai_settings_unknown_family_returns_404(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/no-existe", json={"fields": {}})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_put_ai_settings_unknown_field_returns_400(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"no_existe": "x"}})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_put_ai_settings_store_value_takes_priority_over_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_BASE_URL", "https://env.example.com")
    app = create_app(registry_path=tmp_path / "projects.json", auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.get("/api/admin/ai-settings")
        env_field = next(f for f in response.json()["families"] if f["key"] == "litellm_usage")["fields"][0]
        assert env_field["configured_via"] == "env"

        await client.put("/api/admin/ai-settings/litellm_usage", json={"fields": {"base_url": "https://store.example.com"}})
        response = await client.get("/api/admin/ai-settings")

    field = next(f for f in response.json()["families"] if f["key"] == "litellm_usage")["fields"][0]
    assert field["configured_via"] == "store"
    assert field["value"] == "https://store.example.com"
