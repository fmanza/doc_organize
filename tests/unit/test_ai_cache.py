"""Caché de resultados de IA (M4, G1): reconstruir sin cambios hace cero llamadas; cualquier cambio en lo que se
enviaría vuelve a preguntar."""

import json
import os
import time

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize import ContextBuilder
from doc_organize.ai import AiResultCache, prune_ai_cache
from doc_organize.ai.cache import AI_CACHE_DIR
from doc_organize.core.models import AiSettings, ConversionResult, Project, TaskSettings, TaxonomyEntry
from tests.unit.fake_llm import FakeLlmClient, enrichment, fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

SECRET = "Xq7#Secreto-9931"


def _project(root: Path) -> Project:
    return Project(name="Demo", root_path=str(root), created_at=datetime.now(UTC).isoformat())


def _documents(root: Path, count: int = 3, *, text: str = "sin palabras del catálogo") -> list[ConversionResult]:
    (root / "varios").mkdir(parents=True, exist_ok=True)
    documents = []
    for index in range(count):
        json_path = root / f"d{index}.json"
        json_path.write_text(json.dumps({"title": f"Documento {index}", "chunks": [{"text": f"{text} {index}"}]}), encoding="utf-8")
        (root / f"d{index}.md").write_text("x", encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(root / "varios" / f"d{index}.pdf"), markdown_path=str(root / f"d{index}.md"), json_path=str(json_path), success=True
            )
        )
    return documents


def _manifest(*domains: str):
    return two_axis_manifest(
        [TaxonomyEntry(slug=slug, name=slug.title()) for slug in domains or ("calidad",)], [TaxonomyEntry(slug="politica", name="Política")]
    )


def _ai(*, model: str = "stub-classify", redact: bool = True) -> FakeLlmClient:
    settings = AiSettings(
        base_url="https://proxy.test",
        virtual_key="sk-test",
        rate_limit_retries=0,
        redact_credentials=redact,
        tasks={"classify": TaskSettings(model=model), "enrich": TaskSettings(model="stub-enrich")},
    )
    return fake_client(
        settings=settings,
        classify=lambda request: {request.axes[0]: ("calidad", 0.8), request.axes[1]: ("politica", 0.7)},
        enrich=enrichment(),
    )


async def _build(root: Path, documents, client: FakeLlmClient, manifest=None, **kwargs):
    return await ContextBuilder().build(
        _project(root), documents, taxonomy_manifest=manifest or _manifest(), llm=client, ai_scope="unclassified", enrich=True, **kwargs
    )


def _saved(root: Path) -> str:
    """El contexto en disco sin fechas ni recuentos de IA (que sí cambian entre las dos construcciones)."""
    context = json.loads((root / "context.json").read_text(encoding="utf-8"))
    for key in ("created_at", "updated_at", "ai_stats"):
        context.pop(key)
    indexes = [path.read_text(encoding="utf-8") for path in sorted((root / "domains").glob("*/index.json"))]
    return json.dumps(context, sort_keys=True) + "".join(indexes)


@pytest.mark.asyncio
async def test_rebuilding_without_changes_makes_zero_calls_and_gives_the_same_context(tmp_path) -> None:
    """Puerta de M4: reconstruir sin cambios, cero llamadas."""
    documents = _documents(tmp_path)
    first = await _build(tmp_path, documents, _ai())
    saved = _saved(tmp_path)
    assert first.ai_stats.classification.sent == 3 and first.ai_stats.enrichment.sent == 3

    again = _ai()
    second = await _build(tmp_path, documents, again)

    assert again.proxy.requests == []
    assert (second.ai_stats.classification.sent, second.ai_stats.classification.cached) == (0, 3)
    assert (second.ai_stats.enrichment.sent, second.ai_stats.enrichment.cached) == (0, 3)
    assert _saved(tmp_path) == saved
    assert [item.task for item in second.ai_provenance] == ["classify", "enrich"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["document", "prompt", "model", "catalog", "redaction"])
async def test_any_change_in_what_would_be_sent_asks_again(tmp_path, change: str) -> None:
    """Invalidación por componente (B9)."""
    documents = _documents(tmp_path, 1, text=f"password: {SECRET}")
    await _build(tmp_path, documents, _ai())
    manifest, client = _manifest(), _ai()
    if change == "document":
        documents = _documents(tmp_path, 1, text="texto distinto")
    elif change == "prompt":
        folder = tmp_path / ".doc_organize" / "prompts"
        folder.mkdir(parents=True)
        (folder / "classify.md").write_text(
            "---\nid: classify\nversion: 2\n---\n## system\nJSON.\n$catalog\n## user\n$title $content\n", encoding="utf-8"
        )
    elif change == "model":
        client = _ai(model="otro-modelo")
    elif change == "catalog":
        manifest = _manifest("calidad", "seguridad")
    else:
        client = _ai(redact=False)

    context = await _build(tmp_path, documents, client, manifest)

    assert len(client.proxy.calls("classify")) == 1
    assert context.ai_stats.classification.cached == 0
    # La descripción no depende del catálogo ni del prompt de clasificación: esa sí sale de la caché.
    if change in ("catalog", "prompt", "model"):
        assert context.ai_stats.enrichment.cached == 1


@pytest.mark.asyncio
async def test_cached_documents_do_not_consume_the_budget(tmp_path) -> None:
    documents = _documents(tmp_path, 4)
    first = await _build(tmp_path, documents, _ai(), ai_max_documents=2)
    assert (first.ai_stats.classification.sent, first.ai_stats.classification.stopped) == (2, "budget")

    client = _ai()
    second = await _build(tmp_path, documents, client, ai_max_documents=2)

    assert (second.ai_stats.classification.cached, second.ai_stats.classification.sent) == (2, 2)
    assert second.ai_stats.classification.stopped is None
    assert [request.title for request in client.proxy.calls("classify")] == ["Documento 2", "Documento 3"]


@pytest.mark.asyncio
async def test_the_cache_can_be_turned_off_and_ignores_broken_entries(tmp_path) -> None:
    documents = _documents(tmp_path, 2)
    await _build(tmp_path, documents, _ai())

    off = _ai()
    await _build(tmp_path, documents, off, ai_cache=False)
    assert len(off.proxy.calls("classify")) == 2

    entries = sorted((tmp_path / AI_CACHE_DIR).glob("*/*.json"))
    entries[0].write_text("{roto", encoding="utf-8")
    entries[1].write_text(json.dumps({"v": 1, "response_format": "json_schema", "data": {"otra": "cosa"}}), encoding="utf-8")
    repaired = _ai()
    context = await _build(tmp_path, documents, repaired)
    assert context.ai_stats.classification.sent + context.ai_stats.enrichment.sent == 2  # las dos rotas se vuelven a pedir


@pytest.mark.asyncio
async def test_the_cache_stores_neither_keys_nor_the_redacted_values(tmp_path) -> None:
    await _build(tmp_path, _documents(tmp_path, 1, text=f"password: {SECRET}"), _ai())

    stored = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / AI_CACHE_DIR).glob("*/*.json"))
    assert stored and SECRET not in stored and "sk-test" not in stored


def test_prune_removes_entries_not_used_for_a_while(tmp_path) -> None:
    cache = AiResultCache(tmp_path)
    old, recent = "a" * 64, "b" * 64
    cache.put(old, {"x": 1}, response_format="json_schema")
    cache.put(recent, {"x": 2}, response_format="json_schema")
    long_ago = time.time() - 200 * 86400
    os.utime(cache.directory / old[:2] / f"{old}.json", (long_ago, long_ago))

    assert prune_ai_cache(tmp_path, max_age_days=90) == 1
    assert cache.get(old) is None and cache.get(recent) == ({"x": 2}, "json_schema")


def test_keys_are_validated() -> None:
    with pytest.raises(ValueError):
        AiResultCache("/tmp").get("../../etc/passwd")
