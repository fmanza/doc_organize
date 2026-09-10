"""Tests unitarios de TaxonomyClassificationClient (Sub-fase B, manifiesto de taxonomía)."""

import json

import httpx
import pytest

from pydantic import ValidationError

from doc_organize.ai import TaxonomyClassificationClient, litellm_taxonomy_classification_config_from_env
from doc_organize.core.exceptions import TaxonomyClassificationAuthError, TaxonomyClassificationError
from doc_organize.core.models import LiteLLMTaxonomyClassificationConfig, TaxonomyClassificationResult

_CONFIG = LiteLLMTaxonomyClassificationConfig(base_url="https://litellm.example.com", virtual_key="sk-classify-key")


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


@pytest.mark.asyncio
async def test_classify_returns_both_axes_chosen_by_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-classify-key"
        body = json.loads(request.content)
        assert body["model"] == "claude-classifier"
        assert body["response_format"] == {"type": "json_object"}
        return _chat_response(
            {"domain": "calidad", "domain_confidence": 0.9, "material_type": "normativa", "material_type_confidence": 0.8, "reasoning": "ISO 9001"}
        )

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(
            chunks_text="gestión de calidad ISO 9001",
            title="Política",
            candidate_domains=["calidad", "ciberseguridad"],
            candidate_material_types=["normativa", "procedimiento"],
        )

    assert result.domain == "calidad"
    assert result.domain_confidence == 0.9
    assert result.material_type == "normativa"
    assert result.material_type_confidence == 0.8
    assert result.reasoning == "ISO 9001"


@pytest.mark.asyncio
async def test_classify_never_returns_a_domain_outside_the_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {"domain": "un-dominio-inventado", "domain_confidence": 0.8, "material_type": "normativa", "material_type_confidence": 0.5}
        )

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"], candidate_material_types=["normativa"])

    assert result.domain is None
    assert result.material_type == "normativa"


@pytest.mark.asyncio
async def test_classify_never_returns_a_material_type_outside_the_catalog() -> None:
    """Aunque el modelo "alucine" un valor fuera de la lista de un eje, el cliente no lo propaga
    -- el otro eje se valida y devuelve con normalidad, cada uno contra su propio catálogo."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domain": "calidad", "domain_confidence": 0.7, "material_type": "un-tipo-inventado", "material_type_confidence": 0.9})

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"], candidate_material_types=["normativa"])

    assert result.domain == "calidad"
    assert result.material_type is None


@pytest.mark.asyncio
async def test_classify_with_both_catalogs_empty_never_calls_the_proxy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No debería llamar al proxy sin catálogos candidatos")

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=[], candidate_material_types=[])

    assert result.domain is None
    assert result.material_type is None


@pytest.mark.asyncio
async def test_classify_raises_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyClassificationAuthError):
            await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"], candidate_material_types=["normativa"])


@pytest.mark.asyncio
async def test_classify_raises_taxonomy_classification_error_on_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "esto no es JSON"}}]})

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyClassificationError):
            await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"], candidate_material_types=["normativa"])


@pytest.mark.asyncio
async def test_classify_raises_when_response_is_valid_json_but_not_an_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "null"}}]})

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyClassificationError):
            await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"], candidate_material_types=["normativa"])


@pytest.mark.asyncio
async def test_classify_clamps_out_of_range_confidence_per_axis() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domain": "calidad", "domain_confidence": 2.5, "material_type": "normativa", "material_type_confidence": -3})

    async with TaxonomyClassificationClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.classify(chunks_text="texto", title=None, candidate_domains=["calidad"], candidate_material_types=["normativa"])

    assert result.domain_confidence == 1.0
    assert result.material_type_confidence == 0.0


def test_taxonomy_classification_result_rejects_confidence_outside_0_1() -> None:
    """Defensa en profundidad a nivel de modelo, igual que `DomainClassificationResult` —
    aunque el cliente ya recorta ambas confianzas a [0,1] antes de construir el resultado."""
    with pytest.raises(ValidationError):
        TaxonomyClassificationResult(domain="calidad", domain_confidence=1.5, material_type=None, material_type_confidence=0.0)


def test_litellm_taxonomy_classification_config_from_env_requires_both_vars(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    with pytest.raises(ValueError):
        litellm_taxonomy_classification_config_from_env()


def test_litellm_taxonomy_classification_config_from_env_reads_optional_model(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", "sk-from-env")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL", "claude-haiku")

    config = litellm_taxonomy_classification_config_from_env()

    assert config.base_url == "https://litellm.example.com"
    assert config.virtual_key == "sk-from-env"
    assert config.model == "claude-haiku"


def test_litellm_taxonomy_classification_config_from_env_defaults_model_when_unset(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", "sk-from-env")
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL", raising=False)

    config = litellm_taxonomy_classification_config_from_env()

    assert config.model == "claude-classifier"
