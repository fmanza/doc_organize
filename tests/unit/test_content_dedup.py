"""Duplicados por contenido (2.2.0): mismo texto, contenido parecido con la tarea `dedup`, grupos sin cadenas, documentos
contenidos en otros, índice de vectores, conversión que acompaña al original y exclusión del contexto en modo `copy`."""

from __future__ import annotations

import doctest
import hashlib
import math

from pathlib import Path

import httpx
import numpy as np
import pytest

from doc_organize import ContentDocument, ContentDuplicateFinder, DeduplicationManager, exclude_from_context
from doc_organize.ai.embeddings import EmbeddingIndex
from doc_organize.context.decisions import ClassificationDecisionStore
from doc_organize.core.exceptions import AiConfigurationError
from doc_organize.core.models import AiSettings, ConversionResult, DocumentMetadata, DuplicateReason, TaskSettings
from doc_organize.dedup import content
from tests.unit.fake_llm import FakeRequest, fake_client

FILLER = "Este documento describe con detalle el procedimiento interno y sus responsables en la organización."


def _document(root: Path, name: str, text: str, *, sha: str | None = None, modified: float = 1.0) -> ContentDocument:
    source = root / "origen" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("original", encoding="utf-8")
    markdown = root / "Conversión" / f"{name}.md"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(text, encoding="utf-8")
    metadata = DocumentMetadata(
        full_path=str(source),
        display_name=name,
        extension=name.rsplit(".", 1)[-1],
        size_bytes=1,
        modified_time=modified,
        sha256_hash=sha or hashlib.sha256(name.encode()).hexdigest(),
    )
    conversion = ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=None, success=True)
    return ContentDocument(metadata=metadata, conversion=conversion)


def _text(marker: str, words: int = 40) -> str:
    """Un texto de unas `words` palabras con `marker` (la palabra que decide su vector en `_embedder`)."""
    body = " ".join([FILLER] * (words // 14 + 1))
    return f"{marker} {body} {marker}"


def _angle(degrees: float) -> list[float]:
    return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees))]


#: Vector de cada marcador: alfa y beta se parecen (cos 20° = 0,94), beta y gamma también, alfa y gamma no (cos 40°).
VECTORS = {"alfa": _angle(0), "beta": _angle(20), "gamma": _angle(40), "delta": _angle(90)}


def _embedder(calls: list[list[str]] | None = None):
    def respond(request: FakeRequest) -> list[list[float]]:
        if calls is not None:
            calls.append(list(request.body["input"]))
        return [next(vector for marker, vector in VECTORS.items() if marker in text) for text in request.body["input"]]

    return respond


def _llm(calls: list[list[str]] | None = None, *, with_dedup: bool = True):
    tasks = {"classify": TaskSettings(model="stub-classify")}
    if with_dedup:
        tasks["dedup"] = TaskSettings(model="bge-m3-local")
    settings = AiSettings(base_url="https://proxy.test", virtual_key="sk-test", rate_limit_retries=0, tasks=tasks)
    return fake_client(settings=settings, dedup=_embedder(calls))


def test_examples_in_the_module_docstrings() -> None:
    assert doctest.testmod(content, optionflags=doctest.ELLIPSIS).failed == 0


# --- Mismo contenido (sin IA) ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_text_in_different_files_is_grouped_without_ai(tmp_path) -> None:
    text = _text("alfa")
    docx = _document(tmp_path, "plan.docx", text, modified=2.0)
    pdf = _document(tmp_path, "plan.pdf", f"# {text.upper()}\n\n<!-- image -->", modified=1.0)
    other = _document(tmp_path, "otro.docx", _text("delta") + " distinto")

    report = await ContentDuplicateFinder(tmp_path).find([docx, pdf, other])

    assert [group.reason for group in report.groups] == [DuplicateReason.SAME_CONTENT]
    group = report.groups[0]
    assert group.canonical_doc.display_name == "plan.pdf"  # el más antiguo, como en find_duplicates
    assert [doc.display_name for doc in group.duplicates] == ["plan.docx"]
    assert (group.similarity, group.lexical_similarity, group.contained) == (1.0, 1.0, False)
    assert report.compared == 3 and not report.semantic


@pytest.mark.asyncio
async def test_exact_duplicates_count_once_and_unreadable_or_short_documents_are_reported(tmp_path) -> None:
    same_hash = hashlib.sha256(b"x").hexdigest()
    a = _document(tmp_path, "a.docx", _text("alfa"), sha=same_hash)
    b = _document(tmp_path, "b.docx", _text("alfa"), sha=same_hash)  # duplicado exacto de a: lo agrupa find_duplicates
    short = _document(tmp_path, "portada.docx", "Portada")
    missing = _document(tmp_path, "perdido.docx", _text("alfa"))
    Path(missing.conversion.markdown_path or "").unlink()
    failed = ContentDocument(
        missing.metadata.model_copy(update={"full_path": "/x/fallo.pdf", "sha256_hash": hashlib.sha256(b"fallo").hexdigest()}),
        ConversionResult(source_path="/x/fallo.pdf", success=False),
    )

    report = await ContentDuplicateFinder(tmp_path).find([a, b, short, missing, failed])

    assert report.groups == []
    assert report.compared == 1
    assert sorted(Path(path).name for path in report.not_compared) == ["fallo.pdf", "perdido.docx", "portada.docx"]


# --- Contenido parecido (tarea dedup) ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_pass_needs_its_own_dedup_model(tmp_path) -> None:
    documents = [_document(tmp_path, "a.docx", _text("alfa")), _document(tmp_path, "b.docx", _text("beta"))]

    with pytest.raises(AiConfigurationError, match="cliente de IA"):
        await ContentDuplicateFinder(tmp_path).find(documents, semantic=True)
    with pytest.raises(AiConfigurationError, match="'dedup'"):
        await ContentDuplicateFinder(tmp_path, _llm(with_dedup=False)).find(documents, semantic=True)


@pytest.mark.asyncio
async def test_similar_content_is_grouped_with_the_dedup_task_and_both_scores(tmp_path) -> None:
    llm = _llm()
    a = _document(tmp_path, "contrato.docx", _text("alfa"))
    b = _document(tmp_path, "contrato_v2.docx", _text("beta") + " con una cláusula nueva añadida al final del texto")
    far = _document(tmp_path, "receta.docx", _text("delta"))

    report = await ContentDuplicateFinder(tmp_path, llm, semantic_threshold=0.9).find([a, b, far], semantic=True)

    assert [group.reason for group in report.groups] == [DuplicateReason.SEMANTIC_CONTENT_MATCH]
    group = report.groups[0]
    assert {doc.display_name for doc in [group.canonical_doc, *group.duplicates]} == {"contrato.docx", "contrato_v2.docx"}
    assert group.similarity == pytest.approx(math.cos(math.radians(20)), abs=1e-3)
    assert group.lexical_similarity is not None and 0.5 < group.lexical_similarity < 1.0
    assert not group.contained
    requests = llm.proxy.calls("dedup")
    assert requests and all(request.body["model"] == "bge-m3-local" for request in requests)
    assert llm.proxy.calls("embed") == []  # independiente de los embeddings del contexto
    assert report.semantic and report.embedded == 3


@pytest.mark.asyncio
async def test_groups_do_not_chain_documents_that_are_not_similar_to_each_other(tmp_path) -> None:
    documents = [
        _document(tmp_path, "a.docx", _text("alfa")),
        _document(tmp_path, "b.docx", _text("beta")),
        _document(tmp_path, "c.docx", _text("gamma")),
    ]

    report = await ContentDuplicateFinder(tmp_path, _llm(), semantic_threshold=0.9).find(documents, semantic=True)

    # a~b y b~c llegan al umbral, a~c no: con componentes conexas saldría {a, b, c}.
    assert len(report.groups) == 1
    assert {doc.display_name for doc in [report.groups[0].canonical_doc, *report.groups[0].duplicates]} == {"a.docx", "b.docx"}


@pytest.mark.asyncio
async def test_a_document_contained_in_a_longer_one_is_found_and_flagged(tmp_path) -> None:
    long_text = f"{_text('alfa', 30)} {_text('delta', 30)}"
    longer = _document(tmp_path, "informe_completo.docx", long_text)
    part = _document(tmp_path, "anexo.docx", _text("alfa", 30))
    finder = ContentDuplicateFinder(tmp_path, _llm(), semantic_threshold=0.8, chunk_words=len(_text("alfa", 30).split()), chunk_overlap=0)

    report = await finder.find([longer, part], semantic=True)

    assert len(report.groups) == 1 and report.groups[0].contained
    assert report.groups[0].similarity == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_vectors_are_reused_from_the_project_index(tmp_path) -> None:
    documents = [_document(tmp_path, "a.docx", _text("alfa")), _document(tmp_path, "b.docx", _text("beta"))]
    calls: list[list[str]] = []
    finder = ContentDuplicateFinder(tmp_path, _llm(calls), semantic_threshold=0.9)

    first = await finder.find(documents, semantic=True)
    second = await finder.find(documents, semantic=True)

    assert (first.embedded, second.embedded, second.reused) == (2, 0, 2)
    assert len(calls) == 1
    assert [group.group_id for group in first.groups] == [group.group_id for group in second.groups]  # id estable


@pytest.mark.asyncio
async def test_documents_with_the_same_content_do_not_go_to_the_semantic_pass(tmp_path) -> None:
    calls: list[list[str]] = []
    documents = [
        _document(tmp_path, "a.docx", _text("alfa")),
        _document(tmp_path, "a.pdf", _text("alfa")),
        _document(tmp_path, "b.docx", _text("beta")),
    ]

    report = await ContentDuplicateFinder(tmp_path, _llm(calls), semantic_threshold=0.9).find(documents, semantic=True)

    assert [group.reason for group in report.groups] == [DuplicateReason.SAME_CONTENT]
    assert calls == []  # solo queda b.docx: no hay nada que comparar


def test_finder_validates_its_parameters(tmp_path) -> None:
    for kwargs in ({"semantic_threshold": 0.0}, {"semantic_threshold": 1.5}, {"chunk_words": 10, "chunk_overlap": 10}, {"neighbours": 0}):
        with pytest.raises(ValueError):
            ContentDuplicateFinder(tmp_path, **kwargs)  # type: ignore[arg-type]


def test_chunks_and_pair_similarity() -> None:
    assert content.chunks(["a", "b", "c", "d", "e", "f", "g"], size=3, overlap=1) == ["a b c", "c d e", "e f g"]
    assert content.chunks(["solo"], size=3, overlap=1) == ["solo"]
    identical = np.array([[1.0, 0.0]])
    assert content.pair_similarity(identical, identical) == pytest.approx((1.0, 1.0))
    assert content.jaccard(set(), set()) == 0.0


# --- Índice de vectores con numpy --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_matrix_is_float32_and_keeps_the_disk_format(tmp_path) -> None:
    llm = _llm()
    index = EmbeddingIndex(tmp_path, model="bge-m3-local", redacted=True)

    matrix = await index.matrix(llm, ["alfa uno", "beta dos", "alfa uno"], task="dedup")
    vectors = await EmbeddingIndex(tmp_path, model="bge-m3-local", redacted=True).vectors(llm, ["beta dos"], task="dedup")

    assert matrix.dtype == np.float32 and matrix.shape == (3, 2)
    assert np.array_equal(matrix[0], matrix[2])
    assert vectors == [pytest.approx(VECTORS["beta"], abs=1e-6)]
    assert (index.folder / "vectors.bin").stat().st_size == 2 * 2 * 4  # dos textos distintos, float32


@pytest.mark.asyncio
async def test_embed_refuses_a_task_that_is_not_of_embeddings() -> None:
    with pytest.raises(ValueError, match="embeddings"):
        await _llm().embed(["texto"], task="classify")


# --- Resolver: la conversión acompaña al original ---------------------------------------------------------------------


def _with_conversion_artifacts(document: ContentDocument, root: Path) -> ConversionResult:
    json_path = Path(document.conversion.markdown_path or "").with_suffix(".json")
    json_path.write_text("{}", encoding="utf-8")
    images = root / "Conversión" / "img" / document.metadata.display_name
    images.mkdir(parents=True)
    (images / "imagen.png").write_bytes(b"png")
    return document.conversion.model_copy(update={"json_path": str(json_path), "images_dir": str(images)})


@pytest.mark.asyncio
async def test_moving_a_discarded_document_moves_its_conversion_too(tmp_path) -> None:
    keep = _document(tmp_path, "plan.pdf", _text("alfa"), modified=1.0)
    drop = _document(tmp_path, "plan.docx", _text("alfa"), modified=2.0)
    conversion = _with_conversion_artifacts(drop, tmp_path)
    group = (await ContentDuplicateFinder(tmp_path).find([keep, drop])).groups[0]
    duplicates = tmp_path / "duplicados"

    exact, other, failed = await DeduplicationManager().move_group(
        group,
        duplicates,
        relative_to=tmp_path / "origen",
        conversions={drop.metadata.full_path: conversion},
        conversion_dir=tmp_path / "Conversión",
    )

    assert (exact, other, failed) == (0, 1, [])
    assert (duplicates / "plan.docx").is_file() and not Path(drop.metadata.full_path).exists()
    assert (duplicates / "Conversión" / "plan.docx.md").is_file()
    assert (duplicates / "Conversión" / "plan.docx.json").is_file()
    assert (duplicates / "Conversión" / "img" / "plan.docx" / "imagen.png").is_file()
    assert Path(keep.conversion.markdown_path or "").is_file()  # lo que se conserva no se toca


@pytest.mark.asyncio
async def test_copy_mode_leaves_the_conversion_and_exclude_from_context_records_decisions(tmp_path) -> None:
    keep = _document(tmp_path, "plan.pdf", _text("alfa"), modified=1.0)
    drop = _document(tmp_path, "plan.docx", _text("alfa"), modified=2.0)
    group = (await ContentDuplicateFinder(tmp_path).find([keep, drop])).groups[0]

    await DeduplicationManager().move_group(
        group, tmp_path / "duplicados", mode="copy", relative_to=tmp_path / "origen", conversions={drop.metadata.full_path: drop.conversion}
    )
    saved = await exclude_from_context(tmp_path, [group], roots=[str(tmp_path / "origen")], author="ana")

    assert Path(drop.metadata.full_path).is_file() and Path(drop.conversion.markdown_path or "").is_file()
    decisions = await ClassificationDecisionStore(tmp_path).load()
    assert saved == 1
    assert [(d.document_key, d.action, d.author, d.source_sha256) for d in decisions] == [("plan.docx", "exclude", "ana", drop.metadata.sha256_hash)]
    assert decisions[0].reason == "Duplicado por contenido de «plan.pdf»"
    assert await exclude_from_context(tmp_path, []) == 0


# --- Diagnóstico de la tarea dedup -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_of_dedup_report_served_model_dimension_and_truncation() -> None:
    from doc_organize import AiEndpoint, check_environment

    def proxy(responses: list[list[list[float]]]):
        def handle(request: httpx.Request) -> httpx.Response:
            vectors = responses.pop(0)
            return httpx.Response(200, json={"model": "ollama/bge-m3", "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})

        return httpx.MockTransport(handle)

    endpoint = AiEndpoint(name="dedup", base_url="https://proxy.test", virtual_key="sk-secreta", model="doc-organize-dedup", kind="embedding")
    reads_all = await check_environment(
        check_ai=True, ai_endpoints=[endpoint], build_site=False, transport=proxy([[[0.1] * 4], [[1.0, 0, 0, 0], [0, 1.0, 0, 0]]])
    )
    truncates = await check_environment(
        check_ai=True, ai_endpoints=[endpoint], build_site=False, transport=proxy([[[0.1] * 4], [[1.0] * 4, [1.0] * 4]])
    )

    ok = next(check for check in reads_all.checks if check.name == "ai:dedup")
    assert (ok.status, ok.model, ok.served_model, ok.dimension) == ("ok", "doc-organize-dedup", "ollama/bge-m3", 4)
    assert "responde ollama/bge-m3" in ok.detail and "sk-secreta" not in ok.model_dump_json()
    warning = next(check for check in truncates.checks if check.name == "ai:dedup")
    assert warning.status == "warning" and "corta el texto" in warning.detail


def test_settings_from_env_reads_the_dedup_model(monkeypatch) -> None:
    from doc_organize.ai import settings_from_env

    settings = settings_from_env(
        {
            "DOC_ORGANIZE_LITELLM_BASE_URL": "https://proxy.test",
            "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY": "sk",
            "DOC_ORGANIZE_LITELLM_MODEL_DEDUP": "bge-m3-local",
            "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_DEDUP": "sk-dedup",
        }
    )

    assert settings is not None
    assert (settings.model_for("dedup"), settings.key_for("dedup"), settings.model_for("embed")) == ("bge-m3-local", "sk-dedup", "doc-organize-embed")


# --- Modelo que contesta (para probar un modelo desde un consumidor) ---------------------------------------------------


@pytest.mark.asyncio
async def test_results_say_which_model_answered() -> None:
    import json

    from doc_organize.core.models import AiSettings, TaskSettings

    def embeddings(request: FakeRequest) -> httpx.Response:
        return httpx.Response(200, json={"model": "ollama/bge-m3", "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})

    def chat(request: FakeRequest) -> httpx.Response:
        return httpx.Response(200, json={"model": "qwen2.5:14b", "choices": [{"message": {"content": json.dumps({"ok": True})}}]})

    settings = AiSettings(
        base_url="https://proxy.test",
        virtual_key="sk-test",
        rate_limit_retries=0,
        tasks={"dedup": TaskSettings(model="doc-organize-dedup"), "agent": TaskSettings(model="doc-organize-agent")},
    )
    llm = fake_client(settings=settings, dedup=embeddings, agent=chat)

    embedded = await llm.embed_detailed(["texto"], task="dedup")
    answered = await llm.complete_json(
        "agent",
        [{"role": "user", "content": "ok"}],
        schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
        parse=lambda data: bool(data["ok"]),
    )

    assert (embedded.model, embedded.served_model, embedded.dimension) == ("doc-organize-dedup", "ollama/bge-m3", 3)
    assert (answered.value, answered.model, answered.served_model) == (True, "doc-organize-agent", "qwen2.5:14b")
