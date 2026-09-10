"""Tests unitarios de TaxonomyManifestDraftClient (propuesta de manifiesto de taxonomía por IA)."""

import json

import httpx
import pytest

from doc_organize.ai import TaxonomyManifestDraftClient, litellm_taxonomy_manifest_draft_config_from_env
from doc_organize.ai.taxonomy_manifest_draft_client import SampledDocument
from doc_organize.core.exceptions import TaxonomyManifestDraftAuthError, TaxonomyManifestDraftError
from doc_organize.core.models import LiteLLMTaxonomyManifestDraftConfig

_CONFIG = LiteLLMTaxonomyManifestDraftConfig(base_url="https://litellm.example.com", virtual_key="sk-draft-key")

_SAMPLE = [
    SampledDocument(folder="Ciberseguridad/Politicas", title="Política de seguridad", chunks_text="ISO 27001, controles de acceso"),
    SampledDocument(folder="Calidad/Procedimientos", title="PROC-01 No conformidades", chunks_text="gestión de calidad ISO 9001"),
]


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


_VALID_CONTENT = {
    "domains": [{"slug": "ciberseguridad", "name": "Ciberseguridad"}, {"slug": "calidad", "name": "Calidad"}],
    "material_types": [{"slug": "normativa", "name": "Normativa"}, {"slug": "procedimiento", "name": "Procedimiento"}],
    "reasoning": "Dos áreas temáticas claras en la muestra",
}


@pytest.mark.asyncio
async def test_propose_manifest_returns_the_catalog_proposed_by_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-draft-key"
        body = json.loads(request.content)
        assert body["model"] == "claude-classifier"
        assert body["response_format"] == {"type": "json_object"}
        assert "Ciberseguridad/Politicas" in body["messages"][1]["content"]
        return _chat_response(_VALID_CONTENT)

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.propose_manifest(documents=_SAMPLE)

    assert [entry.slug for entry in result.domains] == ["ciberseguridad", "calidad"]
    assert [entry.slug for entry in result.material_types] == ["normativa", "procedimiento"]
    assert result.reasoning == "Dos áreas temáticas claras en la muestra"


@pytest.mark.asyncio
async def test_propose_manifest_truncates_content_excerpt_per_document() -> None:
    long_document = [SampledDocument(folder="Calidad", title="Manual", chunks_text="x" * 10_000)]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_message = body["messages"][1]["content"]
        assert "x" * 601 not in user_message
        return _chat_response(_VALID_CONTENT)

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        await client.propose_manifest(documents=long_document)


@pytest.mark.asyncio
async def test_propose_manifest_raises_without_calling_the_proxy_when_no_documents() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No debería llamar al proxy sin documentos de muestra")

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(ValueError, match="ningún documento"):
            await client.propose_manifest(documents=[])


@pytest.mark.asyncio
async def test_propose_manifest_dedupes_repeated_slugs_within_the_same_axis() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "domains": [{"slug": "calidad", "name": "Calidad"}, {"slug": "calidad", "name": "Calidad (duplicado)"}],
                "material_types": [{"slug": "normativa", "name": "Normativa"}],
            }
        )

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        result = await client.propose_manifest(documents=_SAMPLE)

    assert [entry.slug for entry in result.domains] == ["calidad"]
    assert result.domains[0].name == "Calidad"


@pytest.mark.asyncio
async def test_propose_manifest_raises_when_domains_axis_is_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domains": [], "material_types": [{"slug": "normativa", "name": "Normativa"}]})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftError, match="ningún dominio"):
            await client.propose_manifest(documents=_SAMPLE)


@pytest.mark.asyncio
async def test_propose_manifest_raises_when_material_types_axis_is_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domains": [{"slug": "calidad", "name": "Calidad"}], "material_types": []})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftError, match="ningún.*tipo de material"):
            await client.propose_manifest(documents=_SAMPLE)


@pytest.mark.asyncio
async def test_propose_manifest_raises_when_an_entry_does_not_match_the_catalog_entry_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"domains": [{"name": "Sin slug"}], "material_types": [{"slug": "normativa", "name": "Normativa"}]})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftError, match="schema"):
            await client.propose_manifest(documents=_SAMPLE)


@pytest.mark.asyncio
async def test_propose_manifest_raises_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftAuthError):
            await client.propose_manifest(documents=_SAMPLE)


@pytest.mark.asyncio
async def test_propose_manifest_raises_on_upstream_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftError):
            await client.propose_manifest(documents=_SAMPLE)


@pytest.mark.asyncio
async def test_propose_manifest_raises_on_malformed_json_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "esto no es JSON"}}]})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftError):
            await client.propose_manifest(documents=_SAMPLE)


@pytest.mark.asyncio
async def test_propose_manifest_raises_when_response_is_valid_json_but_not_an_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "null"}}]})

    async with TaxonomyManifestDraftClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(TaxonomyManifestDraftError):
            await client.propose_manifest(documents=_SAMPLE)


def test_litellm_taxonomy_manifest_draft_config_from_env_requires_both_vars(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY", raising=False)
    with pytest.raises(ValueError):
        litellm_taxonomy_manifest_draft_config_from_env()


def test_litellm_taxonomy_manifest_draft_config_from_env_reads_optional_model(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY", "sk-from-env")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL", "claude-haiku")

    config = litellm_taxonomy_manifest_draft_config_from_env()

    assert config.base_url == "https://litellm.example.com"
    assert config.virtual_key == "sk-from-env"
    assert config.model == "claude-haiku"


def test_litellm_taxonomy_manifest_draft_config_from_env_defaults_model_when_unset(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL", "https://litellm.example.com")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY", "sk-from-env")
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL", raising=False)

    config = litellm_taxonomy_manifest_draft_config_from_env()

    assert config.model == "claude-classifier"
