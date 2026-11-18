"""Servicios por tarea (M4, G1): clasificar ejes, describir y proponer una taxonomía sobre `LlmClient`.

Portan las comprobaciones de los clientes de 1.x que siguen aplicando: catálogo cerrado, confianza acotada, respuestas no
válidas, límites del enriquecimiento y borrador sin repetidos.
"""

import httpx
import pytest

from doc_organize.ai import AxisRequest, PromptRegistry, SampledDocument, classify_document, draft_taxonomy, enrich_document
from doc_organize.ai.services import MAX_CONTENT_CHARS, MAX_SAMPLE_CHARS_PER_DOCUMENT
from doc_organize.core.exceptions import AiAuthError, AiResponseError
from tests.unit.fake_llm import FakeRequest, fake_client

PROMPTS = PromptRegistry()
AXES = [AxisRequest("domains", ["calidad", "seguridad"]), AxisRequest("material_types", ["politica", "manual"])]


async def _classify(respond, axes=AXES, **kwargs):
    client = fake_client(classify=respond)
    async with client:
        result = await classify_document(client, PROMPTS, axes=axes, title="Título", content="texto", **kwargs)
    return result, client


# --- classify_document -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_sends_one_enum_per_axis_and_returns_both() -> None:
    result, client = await _classify(lambda request: {"domains": ("calidad", 0.7), "material_types": ("manual", 0.6), "reasoning": " Por el título "})

    properties = client.proxy.requests[0].body["response_format"]["json_schema"]["schema"]["properties"]
    assert properties["domains"]["properties"]["value"]["enum"] == ["calidad", "seguridad", None]
    assert properties["material_types"]["properties"]["value"]["enum"] == ["politica", "manual", None]
    assert (result.value.axes["domains"].slug, result.value.axes["domains"].confidence) == ("calidad", 0.7)
    assert result.value.axes["material_types"].slug == "manual"
    assert result.value.reasoning == "Por el título"
    assert "domains: calidad, seguridad" in client.proxy.requests[0].text


@pytest.mark.asyncio
async def test_classify_never_returns_a_value_outside_the_catalog() -> None:
    """Aunque un modelo sin `json_schema` estricto se lo invente, el valor no pasa la validación."""

    def respond(request: FakeRequest) -> dict:
        return {"reasoning": None, "domains": {"value": "inventado", "confidence": 0.9}, "material_types": {"value": None, "confidence": 0.1}}

    result, _ = await _classify(respond)

    assert result.value.axes["domains"].slug is None
    assert result.value.axes["material_types"].slug is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "expected"), [(1.7, 1.0), (-0.3, 0.0), ("no", 0.0)])
async def test_classify_clamps_confidence(raw, expected) -> None:
    def respond(request: FakeRequest) -> dict:
        return {"reasoning": None, "domains": {"value": "calidad", "confidence": raw}, "material_types": {"value": None, "confidence": 0}}

    result, _ = await _classify(respond)

    assert result.value.axes["domains"].confidence == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["no es json", "[1]", '{"reasoning": null}'])
async def test_classify_rejects_answers_without_the_axes(content: str) -> None:
    def respond(_request: FakeRequest) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with pytest.raises(AiResponseError):
        await _classify(respond)


@pytest.mark.asyncio
async def test_classify_needs_at_least_one_axis_and_truncates_the_content() -> None:
    with pytest.raises(ValueError, match="eje"):
        await classify_document(fake_client(), PROMPTS, axes=[], title=None, content="x")

    client = fake_client(classify=lambda request: {"domains": "calidad"})
    async with client:
        await classify_document(client, PROMPTS, axes=AXES[:1], title=None, content="a" * (MAX_CONTENT_CHARS + 500))

    sent = client.proxy.requests[0].body["messages"][-1]["content"]
    assert "a" * MAX_CONTENT_CHARS in sent and "a" * (MAX_CONTENT_CHARS + 1) not in sent
    assert "Título: (sin título)" in sent


@pytest.mark.asyncio
async def test_classify_auth_error_propagates() -> None:
    with pytest.raises(AiAuthError):
        await _classify(lambda _request: httpx.Response(401))


# --- enrich_document --------------------------------------------------------------------------------------------------


async def _enrich(answer: object):
    client = fake_client(enrich=lambda _request: answer)
    async with client:
        return await enrich_document(client, PROMPTS, title="Informe", content="texto")


@pytest.mark.asyncio
async def test_enrich_cleans_the_answer_and_keeps_at_most_eight_keywords() -> None:
    result = await _enrich({"description": "  Informe   anual\n de calidad ", "keywords": [f"clave {n}" for n in range(12)] + ["clave 0", " ", 7]})

    assert result.value.description == "Informe anual de calidad"
    assert result.value.keywords == [f"clave {n}" for n in range(8)]


@pytest.mark.asyncio
async def test_enrich_accepts_a_null_description_and_rejects_non_list_keywords() -> None:
    assert (await _enrich({"description": None, "keywords": []})).value.description is None
    with pytest.raises(AiResponseError):
        await _enrich({"description": "x", "keywords": "uno, dos"})


# --- draft_taxonomy ---------------------------------------------------------------------------------------------------


def _entry(slug: str) -> dict:
    return {"slug": slug, "name": slug.title(), "description": None, "keywords": []}


async def _draft(answer: object, documents=None):
    client = fake_client(taxonomy_design=lambda _request: answer)
    sample = documents or [SampledDocument(folder="Calidad", title="Manual", chunks_text="texto")]
    async with client:
        return await draft_taxonomy(client, PROMPTS, sample), client


@pytest.mark.asyncio
async def test_draft_returns_the_catalog_without_repeated_slugs_and_truncates_each_document() -> None:
    answer = {
        "domains": [_entry("calidad"), _entry("calidad"), _entry("seguridad")],
        "material_types": [_entry("manual")],
        "reasoning": "Por carpetas",
    }
    documents = [SampledDocument(folder="Calidad", title="Manual", chunks_text="b" * (MAX_SAMPLE_CHARS_PER_DOCUMENT + 100))]

    result, client = await _draft(answer, documents)

    assert [entry.slug for entry in result.value.domains] == ["calidad", "seguridad"]
    assert result.value.to_manifest().subfolder_axis.entries[0].slug == "manual"
    sent = client.proxy.requests[0].text
    assert "1. Carpeta: Calidad | Título: Manual" in sent
    assert "b" * MAX_SAMPLE_CHARS_PER_DOCUMENT in sent and "b" * (MAX_SAMPLE_CHARS_PER_DOCUMENT + 1) not in sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        {"domains": [], "material_types": [_entry("manual")], "reasoning": None},
        {"domains": [_entry("calidad")], "material_types": [], "reasoning": None},
        {"domains": [{"slug": "sin-nombre"}], "material_types": [_entry("manual")], "reasoning": None},
        [1, 2],
    ],
)
async def test_draft_rejects_an_unusable_answer(answer) -> None:
    with pytest.raises(AiResponseError):
        await _draft(answer)


@pytest.mark.asyncio
async def test_draft_without_documents_never_calls_the_proxy() -> None:
    client = fake_client()
    with pytest.raises(ValueError, match="muestra"):
        await draft_taxonomy(client, PROMPTS, [])
    assert client.proxy.requests == []
