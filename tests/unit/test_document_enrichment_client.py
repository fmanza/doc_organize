"""DocumentEnrichmentClient (1.5.0): descripción y palabras clave por IA vía LiteLLM Proxy, sin red (MockTransport)."""

import json

import httpx
import pytest

from doc_organize.ai import DocumentEnrichmentClient, litellm_enrichment_config_from_env
from doc_organize.core.exceptions import DocumentEnrichmentAuthError, DocumentEnrichmentConnectionError, DocumentEnrichmentError
from doc_organize.core.models import LiteLLMEnrichmentConfig

_CONFIG = LiteLLMEnrichmentConfig(base_url="https://litellm.example.com", virtual_key="sk-enrich-key")


def _client(handler) -> DocumentEnrichmentClient:  # type: ignore[no-untyped-def]
    return DocumentEnrichmentClient(_CONFIG, transport=httpx.MockTransport(handler))


def _chat(content: object) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


@pytest.mark.asyncio
async def test_enrich_sends_a_json_request_and_cleans_the_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-enrich-key"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "x" * 4000 in body["messages"][1]["content"]
        assert "x" * 4001 not in body["messages"][1]["content"]
        return _chat({"description": "  Procedimiento de\n auditoría ", "keywords": ["auditoría", "Auditoría", 3, "ISO 19011"]})

    async with _client(handler) as client:
        result = await client.enrich(chunks_text="x" * 5000, title="PR-07")

    assert result.description == "Procedimiento de auditoría"
    assert result.keywords == ["auditoría", "ISO 19011"]


@pytest.mark.asyncio
async def test_enrich_keeps_at_most_eight_keywords() -> None:
    async with _client(lambda request: _chat({"description": "d", "keywords": [f"k{i}" for i in range(20)]})) as client:
        result = await client.enrich(chunks_text="texto", title=None)
    assert result.keywords == [f"k{i}" for i in range(8)]


@pytest.mark.asyncio
async def test_enrich_ignores_values_that_are_not_text() -> None:
    async with _client(lambda request: _chat({"description": {"no": "texto"}, "keywords": "uno, dos"})) as client:
        result = await client.enrich(chunks_text="texto", title=None)
    assert result.description is None
    assert result.keywords == ["uno", "dos"]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [[], "texto", None])
async def test_enrich_rejects_an_answer_that_is_not_a_json_object(content: object) -> None:
    async with _client(lambda request: _chat(content)) as client:
        with pytest.raises(DocumentEnrichmentError, match="no es un objeto JSON"):
            await client.enrich(chunks_text="texto", title=None)


@pytest.mark.asyncio
async def test_enrich_maps_401_to_an_auth_error_without_leaking_the_key() -> None:
    async with _client(lambda request: httpx.Response(401, json={"error": "invalid key"})) as client:
        with pytest.raises(DocumentEnrichmentAuthError) as exc_info:
            await client.enrich(chunks_text="texto", title=None)
    assert "sk-enrich-key" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_enrich_maps_network_errors_to_a_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    async with _client(handler) as client:
        with pytest.raises(DocumentEnrichmentConnectionError):
            await client.enrich(chunks_text="texto", title=None)


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_ENRICHMENT_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="DOC_ORGANIZE_LITELLM_ENRICHMENT_BASE_URL"):
        litellm_enrichment_config_from_env()

    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_ENRICHMENT_BASE_URL", "https://proxy")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_ENRICHMENT_VIRTUAL_KEY", "sk-x")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL", "describe")
    config = litellm_enrichment_config_from_env()
    assert (config.base_url, config.virtual_key, config.model) == ("https://proxy", "sk-x", "describe")
