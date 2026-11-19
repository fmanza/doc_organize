"""ContextBuilder sobre el cliente único de IA (M4, G1): `llm`/`ai_scope`/`enrich`, `ai_stats` y `ai_provenance`."""

import json

from datetime import UTC, datetime

import pytest

from doc_organize import ContextBuilder, ContextRegistry
from doc_organize.core.models import Context, ConversionResult, Project, TaxonomyEntry
from tests.unit.fake_llm import enrichment, fake_client, taxonomy_ai
from tests.unit.taxonomy_helpers import two_axis_manifest


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _documents(tmp_path, count: int = 2) -> list[ConversionResult]:
    (tmp_path / "varios").mkdir(exist_ok=True)
    documents = []
    for index in range(count):
        json_path = tmp_path / f"d{index}.json"
        json_path.write_text(json.dumps({"title": f"Documento {index}", "chunks": [{"text": "sin palabras del catálogo"}]}), encoding="utf-8")
        (tmp_path / f"d{index}.md").write_text("x", encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(tmp_path / "varios" / f"d{index}.pdf"),
                markdown_path=str(tmp_path / f"d{index}.md"),
                json_path=str(json_path),
                success=True,
            )
        )
    return documents


_MANIFEST = two_axis_manifest([TaxonomyEntry(slug="calidad", name="Calidad")], [TaxonomyEntry(slug="politica", name="Política")])


@pytest.mark.asyncio
async def test_stats_tokens_and_provenance_are_recorded(tmp_path) -> None:
    client = taxonomy_ai("calidad", 0.9, "politica", 0.8, enrich=enrichment())

    context = await ContextBuilder().build(
        _project(tmp_path), _documents(tmp_path), taxonomy_manifest=_MANIFEST, llm=client, ai_scope="unclassified", enrich=True
    )

    stats = context.ai_stats
    assert (stats.scope, stats.enrich) == ("unclassified", True)
    assert (stats.classification.sent, stats.classification.assigned, stats.classification.failed) == (2, 2, 0)
    assert (stats.classification.prompt_tokens, stats.classification.completion_tokens) == (200, 20)
    assert stats.classification.response_format == "json_schema"
    assert stats.enrichment.sent == 2
    assert [(item.task, item.prompt_id, item.source, item.model) for item in context.ai_provenance] == [
        ("classify", "classify", "builtin", "stub-classify"),
        ("enrich", "enrich", "builtin", "stub-enrich"),
    ]
    reloaded = await ContextRegistry().load_context(_project(tmp_path))
    assert reloaded.ai_stats == stats and reloaded.ai_provenance == context.ai_provenance


@pytest.mark.asyncio
async def test_a_project_prompt_is_used_and_recorded(tmp_path) -> None:
    folder = tmp_path / ".doc_organize" / "prompts"
    folder.mkdir(parents=True)
    (folder / "classify.md").write_text(
        "---\nid: classify-vd\nversion: 2\n---\n## system\nClasifica en JSON con el catálogo.\n$catalog\n## user\nMARCA-PROYECTO $title\n$content\n",
        encoding="utf-8",
    )
    client = taxonomy_ai("calidad", 0.9, "politica", 0.8)

    context = await ContextBuilder().build(
        _project(tmp_path), _documents(tmp_path, 1), taxonomy_manifest=_MANIFEST, llm=client, ai_scope="unclassified"
    )

    assert "MARCA-PROYECTO" in client.sent_texts[0]
    [provenance] = context.ai_provenance
    assert (provenance.prompt_id, provenance.version, provenance.source) == ("classify-vd", "2", "project")


@pytest.mark.asyncio
async def test_without_ai_there_are_no_calls_stats_or_provenance(tmp_path) -> None:
    client = fake_client()

    context = await ContextBuilder().build(_project(tmp_path), _documents(tmp_path), taxonomy_manifest=_MANIFEST, llm=client)

    assert client.proxy.requests == []
    assert (context.ai_stats.scope, context.ai_stats.classification.sent, context.ai_provenance) == ("off", 0, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"ai_scope": "unclassified"}, {"enrich": True}])
async def test_asking_for_ai_without_a_client_is_an_error(tmp_path, kwargs) -> None:
    with pytest.raises(ValueError, match="llm"):
        await ContextBuilder().build(_project(tmp_path), _documents(tmp_path, 1), **kwargs)


def test_a_1_x_context_keeps_its_ai_counts_and_models() -> None:
    context = Context.model_validate(
        {
            "project_name": "P",
            "created_at": "a",
            "updated_at": "b",
            "ai_classification_enabled": True,
            "ai_classification_model": "modelo-viejo",
            "ai_documents_sent": 5,
            "ai_documents_classified": 3,
            "ai_documents_failed": 1,
            "ai_classification_stopped": "budget",
            "ai_enrichment_enabled": True,
            "ai_enrichment_sent": 2,
            "ai_enrichment_applied": 2,
        }
    )

    assert context.ai_stats.scope == "unclassified" and context.ai_stats.enrich is True
    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned, context.ai_stats.classification.stopped) == (
        5,
        3,
        "budget",
    )
    assert context.ai_stats.enrichment.assigned == 2
    assert context.model_for_task("classify") == "modelo-viejo" and context.model_for_task("enrich") is None
