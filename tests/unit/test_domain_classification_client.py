"""Tests unitarios de DomainClassificationClient (Sub-fase B, clasificación por IA)."""

import json

import httpx
import pytest

from pydantic import ValidationError

from doc_organize.ai import DomainClassificationClient, litellm_classification_config_from_env
from doc_organize.core.exceptions import DomainClassificationAuthError, DomainClassificationError
from doc_organize.core.models import DomainClassificationResult, LiteLLMClassificationConfig

_CONFIG = LiteLLMClassificationConfig(base_url="https://litellm.example.com", virtual_key="sk-classify-key")


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


@pytest.mark.asyncio
async def test_classify_returns_domain_chosen_by_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-classify-key"
        body = json.loads(request.content)
        assert body["model"] == "claude-classifier"
        assert body["response_format"] == {"type": "json_object"}
        return _chat_response({"domain": "calidad", "confidence": 0.9, "reasoning": "Menciona ISO 9001"})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="gestión de calidad ISO 9001", title="Política", candidate_domains=["calidad", "ciberseguridad"])

    assert result.domain == "calidad"
    assert result.confidence == 0.9
    assert result.reasoning == "Menciona ISO 9001"


@pytest.mark.asyncio
async def test_classify_never_returns_a_domain_outside_the_catalog() -> None:
    """Aunque el modelo "alucine" un dominio fuera de la lista, el cliente no lo propaga."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domain": "un-dominio-inventado", "confidence": 0.8, "reasoning": "..."})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad", "ciberseguridad"])

    assert result.domain is None


@pytest.mark.asyncio
async def test_classify_with_empty_catalog_never_calls_the_proxy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No debería llamar al proxy sin catálogo de dominios")

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=[])

    assert result.domain is None


@pytest.mark.asyncio
async def test_classify_raises_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(DomainClassificationAuthError):
            await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"])


@pytest.mark.asyncio
async def test_classify_raises_domain_classification_error_on_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "esto no es JSON"}}]})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(DomainClassificationError):
            await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"])


@pytest.mark.asyncio
async def test_classify_raises_when_response_is_valid_json_but_not_an_object() -> None:
    """`json.loads("null")`/`"42"` no fallan, pero tampoco tienen `.get()` — antes
    de la corrección esto tumbaba toda la petición con un AttributeError sin capturar."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "null"}}]})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(DomainClassificationError):
            await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"])


@pytest.mark.asyncio
async def test_classify_clamps_out_of_range_confidence_to_zero_one() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domain": "calidad", "confidence": 2.5, "reasoning": "..."})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"])

    assert result.confidence == 1.0


def test_domain_classification_result_rejects_confidence_outside_0_1() -> None:
    """Defensa en profundidad a nivel de modelo: aunque `DomainClassificationClient`
    ya recorta `confidence` a [0,1] antes de construir el resultado (ver arriba),
    el propio modelo también lo exige — por si un llamador futuro no recorta."""
    with pytest.raises(ValidationError):
        DomainClassificationResult(domain="calidad", confidence=1.5, reasoning=None)


@pytest.mark.asyncio
async def test_classify_clamps_negative_confidence_to_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domain": "calidad", "confidence": -3, "reasoning": "..."})

    async with DomainClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"])

    assert result.confidence == 0.0


def test_litellm_classification_config_from_env_requires_both_vars(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    with pytest.raises(ValueError):
        litellm_classification_config_from_env()


def test_litellm_classification_config_from_env_reads_optional_model(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-from-env")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL", "claude-haiku")

    config = litellm_classification_config_from_env()

    assert config.base_url == "https://litellm.example.com"
    assert config.virtual_key == "sk-from-env"
    assert config.model == "claude-haiku"


def test_litellm_classification_config_from_env_defaults_model_when_unset(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-from-env")
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL", raising=False)

    config = litellm_classification_config_from_env()

    assert config.model == "claude-classifier"
