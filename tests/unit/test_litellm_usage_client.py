"""Tests unitarios de LiteLLMUsageClient (fase 2 IA, monitorización de uso/coste)."""

import httpx
import pytest

from doc_organize.ai import LiteLLMUsageClient, litellm_usage_config_from_env
from doc_organize.core.exceptions import UsageSourceAuthError, UsageSourceError
from doc_organize.core.models import LiteLLMUsageConfig, UsageSourceName

_CONFIG = LiteLLMUsageConfig(base_url="https://litellm.example.com", virtual_key="sk-test-key")


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_get_usage_returns_spend_from_key_info() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/key/info"
        assert request.url.params["key"] == "sk-test-key"
        assert request.headers["authorization"] == "Bearer sk-test-key"
        return httpx.Response(200, json={"key": "sk-test-key", "info": {"spend": 1.5, "key_alias": "doc-organize"}})

    async with LiteLLMUsageClient(_CONFIG, transport=_transport(handler)) as client:
        snapshot = await client.get_usage()

    assert snapshot.source == UsageSourceName.LITELLM
    assert len(snapshot.items) == 1
    assert snapshot.items[0].cost_usd == 1.5
    assert snapshot.items[0].sku == "doc-organize"


@pytest.mark.asyncio
async def test_get_usage_accepts_explicit_key_override() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "sk-other-key"
        return httpx.Response(200, json={"info": {"spend": 0.0}})

    async with LiteLLMUsageClient(_CONFIG, transport=_transport(handler)) as client:
        await client.get_usage(key="sk-other-key")


@pytest.mark.asyncio
async def test_get_usage_raises_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    async with LiteLLMUsageClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(UsageSourceAuthError):
            await client.get_usage()


@pytest.mark.asyncio
async def test_get_usage_raises_usage_source_error_on_other_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    async with LiteLLMUsageClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(UsageSourceError):
            await client.get_usage()


def test_litellm_usage_config_from_env_requires_both_vars(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_VIRTUAL_KEY", raising=False)
    with pytest.raises(ValueError):
        litellm_usage_config_from_env()


def test_litellm_usage_config_from_env_reads_both_vars(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_VIRTUAL_KEY", "sk-from-env")

    config = litellm_usage_config_from_env()

    assert config.base_url == "https://litellm.example.com"
    assert config.virtual_key == "sk-from-env"
