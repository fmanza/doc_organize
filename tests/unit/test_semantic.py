"""Embeddings y sub-fase semántica (M7, G4): índice con caché, asignación por similitud, empates, ejes decididos y
fallos del modelo."""

import json

from datetime import UTC, datetime

import httpx
import pytest

from doc_organize import ClassificationDecision, ContextBuilder
from doc_organize.ai.embeddings import EMBEDDINGS_DIR, EmbeddingIndex
from doc_organize.context.semantic import best_values
from doc_organize.core.exceptions import AiResponseError
from doc_organize.core.models import ConversionResult, Project, TaxonomyAxis, TaxonomyEntry
from doc_organize.utils.folding import fold
from tests.unit.fake_llm import FakeRequest, fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

VOCABULARY = ("auditor", "proceso", "red", "cifrado", "procedimiento", "pasos", "normativ")


def _vector(text: str) -> list[float]:
    folded = fold(text)
    return [float(folded.count(root)) for root in VOCABULARY] + [0.01]


def _embedder(calls: list[list[str]] | None = None):
    def respond(request: FakeRequest) -> list[list[float]]:
        if calls is not None:
            calls.append(list(request.body["input"]))
        return [_vector(text) for text in request.body["input"]]

    return respond


# --- Índice ------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_keeps_vectors_and_only_asks_for_new_texts(tmp_path) -> None:
    calls: list[list[str]] = []
    llm = fake_client(embed=_embedder(calls))
    async with llm:
        index = EmbeddingIndex(tmp_path, model="emb", redacted=True)
        first = await index.vectors(llm, ["auditoria de procesos", "red y cifrado", "auditoria de procesos"], batch_size=1)
        again = EmbeddingIndex(tmp_path, model="emb", redacted=True)
        second = await again.vectors(llm, ["red y cifrado", "otro texto"])

    assert calls == [["auditoria de procesos"], ["red y cifrado"], ["otro texto"]]
    assert first[0] == first[2] == pytest.approx(_vector("auditoria de procesos"))
    assert second[0] == pytest.approx(first[1])
    assert (index.embedded, index.reused, again.embedded, again.reused) == (2, 0, 1, 1)
    assert len(list((tmp_path / EMBEDDINGS_DIR).iterdir())) == 1


@pytest.mark.asyncio
async def test_a_damaged_index_is_rebuilt_and_mixed_dimensions_are_refused(tmp_path) -> None:
    llm = fake_client(embed=_embedder())
    async with llm:
        index = EmbeddingIndex(tmp_path, model="emb", redacted=True)
        await index.vectors(llm, ["auditoria"])
        (index.folder / "vectors.bin").write_bytes(b"roto")
        assert await index.vectors(llm, ["auditoria"]) == [pytest.approx(_vector("auditoria"))]
        assert index.embedded == 2

    other = fake_client(embed=lambda request: [[1.0, 2.0] for _ in request.body["input"]])
    async with other:
        with pytest.raises(AiResponseError, match="dimensión"):
            await EmbeddingIndex(tmp_path, model="emb", redacted=True).vectors(other, ["nuevo"])


def test_best_values_needs_the_threshold_and_a_margin_on_single_axes() -> None:
    entries = [("a", [1.0, 0.0]), ("b", [0.99, 0.14]), ("c", [0.0, 1.0])]

    assert best_values([1.0, 0.0], entries, multiple=False, threshold=0.5) == []  # «a» y «b» casi empatan
    assert best_values([1.0, 0.0], entries[::2], multiple=False, threshold=0.5) == [("a", 1.0)]
    assert best_values([0.7, 0.7], entries[::2], multiple=False, threshold=0.75) == []
    assert [slug for slug, _ in best_values([1.0, 0.1], entries, multiple=True, threshold=0.9)] == ["b", "a"]  # del más parecido al menos


# --- En la construcción ------------------------------------------------------------------------------------------------


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, stem: str, text: str) -> ConversionResult:
    (tmp_path / "entrada").mkdir(exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": stem, "chunks": [{"text": text}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
    return ConversionResult(
        source_path=str(tmp_path / "entrada" / f"{stem}.pdf"), markdown_path=str(tmp_path / f"{stem}.md"), json_path=str(json_path), success=True
    )


def _manifest():
    domains = [
        TaxonomyEntry(slug="calidad", name="Calidad", description="Auditorias internas y mejora de procesos"),
        TaxonomyEntry(slug="seguridad", name="Seguridad", description="Redes y cifrado"),
    ]
    types = [
        TaxonomyEntry(slug="procedimiento", name="Procedimiento", description="Procedimiento con pasos"),
        TaxonomyEntry(slug="normativa", name="Norma", description="Normativa externa"),
    ]
    topics = TaxonomyAxis(
        key="topics",
        name="Temas",
        multiple=True,
        rules=False,
        entries=[
            TaxonomyEntry(slug="auditoria", name="Auditoría", description="auditorias de procesos"),
            TaxonomyEntry(slug="redes", name="Redes", description="red"),
        ],
    )
    return two_axis_manifest(domains, types, extra_axes=[topics])


TEXT = "Este documento explica como se hacen las auditorias de los procesos, paso a paso, con un procedimiento claro y sus pasos."


@pytest.mark.asyncio
async def test_semantic_fills_empty_axes_before_the_ai(tmp_path) -> None:
    document = _document(tmp_path, "doc", TEXT)
    llm = fake_client(embed=_embedder(), classify=lambda request: dict.fromkeys(request.axes))

    context = await ContextBuilder().build(
        _project(tmp_path),
        [document],
        taxonomy_manifest=_manifest(),
        llm=llm,
        semantic=True,
        semantic_threshold=0.6,
        ai_scope="missing_axes",
        ai_cache=False,
    )

    [domain] = context.domains
    [result] = domain.documents
    assert domain.slug == "calidad" and result.classified_by == "semantic"
    assert {key: [(v.slug, v.classified_by) for v in values] for key, values in result.classification.axes.items()} == {
        "domains": [("calidad", "semantic")],
        "material_types": [("procedimiento", "rules")],  # lo resolvieron las reglas: la semántica no lo toca
        "topics": [("auditoria", "semantic")],
    }
    assert llm.proxy.calls("classify") == []  # no quedó nada vacío para la IA
    stats = context.ai_stats
    assert stats.semantic is True
    assert (stats.semantic_classification.assigned, stats.semantic_classification.sent) == (1, 5)  # 4 valores (dominios y temas) + 1 documento


@pytest.mark.asyncio
async def test_semantic_reuses_the_index_and_respects_decisions(tmp_path) -> None:
    document = _document(tmp_path, "doc", TEXT)
    decision = ClassificationDecision(document_key="doc.pdf", action="set_axis", axes={"topics": []})
    options = {"taxonomy_manifest": _manifest(), "semantic": True, "semantic_threshold": 0.6, "ai_cache": False, "decisions": [decision]}

    first = await ContextBuilder().build(_project(tmp_path), [document], llm=fake_client(embed=_embedder()), **options)
    calls: list[list[str]] = []
    second = await ContextBuilder().build(_project(tmp_path), [document], llm=fake_client(embed=_embedder(calls)), **options)

    assert first.domains[0].documents[0].classification.slugs("topics") == []  # «ninguno» decidido por una persona
    assert calls == [] and second.ai_stats.semantic_classification.cached == 3  # 2 dominios (los temas los decidió una persona) + documento


@pytest.mark.asyncio
async def test_an_embedding_failure_does_not_stop_the_build(tmp_path) -> None:
    document = _document(tmp_path, "doc", TEXT)

    context = await ContextBuilder().build(
        _project(tmp_path),
        [document],
        taxonomy_manifest=_manifest(),
        llm=fake_client(embed=lambda request: httpx.Response(500)),
        semantic=True,
        ai_cache=False,
    )

    assert context.ai_stats.semantic_classification.failed == 1
    assert context.domains[0].slug == "sin-clasificar"


@pytest.mark.asyncio
async def test_semantic_needs_a_client_and_a_valid_threshold(tmp_path) -> None:
    with pytest.raises(ValueError, match="semantic"):
        await ContextBuilder().build(_project(tmp_path), [], semantic=True)
    with pytest.raises(ValueError, match="semantic_threshold"):
        await ContextBuilder().build(_project(tmp_path), [], llm=fake_client(), semantic=True, semantic_threshold=1.5)


@pytest.mark.asyncio
async def test_index_info_and_clear(tmp_path) -> None:
    """Petición de la web (W6): ver cuánto ocupa el índice y poder vaciarlo."""
    from doc_organize.ai.embeddings import clear_embedding_index, embedding_index_info

    llm = fake_client(embed=_embedder())
    await EmbeddingIndex(tmp_path, model="modelo-a", redacted=True).vectors(llm, ["auditoria", "red", "cifrado"])
    await EmbeddingIndex(tmp_path, model="modelo-b", redacted=True).vectors(llm, ["proceso"])

    info = {item.model: item for item in embedding_index_info(tmp_path)}
    assert (info["modelo-a"].vectors, info["modelo-a"].dimension) == (3, len(VOCABULARY) + 1)
    assert info["modelo-b"].vectors == 1 and all(item.size_bytes > 0 for item in info.values())

    assert clear_embedding_index(tmp_path, model="modelo-a") == 1
    assert [item.model for item in embedding_index_info(tmp_path)] == ["modelo-b"]
    assert clear_embedding_index(tmp_path) == 1 and embedding_index_info(tmp_path) == []
