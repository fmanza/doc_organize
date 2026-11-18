"""Rendimiento de la construcción (M2, B): un `.json` leído una vez sin IA y llamadas a la IA en paralelo con el mismo
resultado que en serie."""

import asyncio
import json
import random

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_organize.context import context_builder as builder_module
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.core.exceptions import OperationCancelledError
from doc_organize.core.models import (
    ConversionResult,
    DocumentEnrichmentResult,
    DomainClassificationResult,
    Project,
    TaxonomyAxis,
    TaxonomyClassificationResult,
    TaxonomyEntry,
)
from doc_organize.core.progress import CancelToken
from tests.unit.taxonomy_helpers import two_axis_manifest


def _project(root: Path) -> Project:
    return Project(name="Demo", root_path=str(root), created_at=datetime.now(UTC).isoformat())


def _documents(root: Path, count: int, *, folder: str = "varios", text: str = "texto sin catálogo") -> list[ConversionResult]:
    (root / folder).mkdir(parents=True, exist_ok=True)
    documents = []
    for index in range(count):
        json_path = root / f"doc{index}.json"
        json_path.write_text(json.dumps({"title": f"Documento {index}", "chunks": [{"text": f"{text} {index}"}]}), encoding="utf-8")
        (root / f"doc{index}.md").write_text("x", encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(root / folder / f"doc{index}.pdf"), markdown_path=str(root / f"doc{index}.md"), json_path=str(json_path), success=True
            )
        )
    return documents


def _manifest():
    frameworks = TaxonomyAxis(key="frameworks", name="Marcos", multiple=True, entries=[TaxonomyEntry(slug="ens", name="ENS")])
    return two_axis_manifest(
        [TaxonomyEntry(slug="calidad", name="Calidad"), TaxonomyEntry(slug="seguridad", name="Seguridad")],
        [TaxonomyEntry(slug="politica", name="Política"), TaxonomyEntry(slug="manual", name="Manual")],
        extra_axes=[frameworks],
    )


@pytest.fixture
def read_counter(monkeypatch) -> Counter:
    """Cuenta las lecturas de cada `.json` que hace el builder."""
    counts: Counter = Counter()
    original = builder_module.read_conversion_json

    async def counting(json_path: str):
        counts[json_path] += 1
        return await original(json_path)

    monkeypatch.setattr(builder_module, "read_conversion_json", counting)
    return counts


# --- Lectura única ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_without_ai_each_json_is_read_once_in_manifest_mode(tmp_path, read_counter) -> None:
    documents = _documents(tmp_path, 6, text="politica de calidad del ENS")

    context = await ContextBuilder().build(_project(tmp_path), documents, taxonomy_manifest=_manifest())

    assert set(read_counter.values()) == {1}
    assert len(read_counter) == 6
    assert sum(len(domain.documents) for domain in context.domains) == 6


@pytest.mark.asyncio
async def test_without_ai_each_json_is_read_once_without_manifest(tmp_path, read_counter) -> None:
    classified = _documents(tmp_path / "a", 3, folder="calidad", text="procedimiento de auditoría interna del sistema de gestión de calidad")
    below = _documents(tmp_path / "b", 3, folder="varios")

    context = await ContextBuilder().build(_project(tmp_path), [*classified, *below], candidate_domains=["calidad", "obras"])

    assert len(read_counter) == 6 and set(read_counter.values()) == {1}
    assert [detail.reason for detail in context.unclassified_details] == ["below_threshold"] * 3
    assert {document.language for domain in context.domains for document in domain.documents} == {"es"}


# --- IA en paralelo --------------------------------------------------------------------------------------------------


class _SlowTaxonomyAI:
    """Responde según el número del documento, tras una espera aleatoria; mide cuántas llamadas hay a la vez."""

    config = SimpleNamespace(model="stub")

    def __init__(self, seed: int) -> None:
        self.random = random.Random(seed)
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def classify(self, *, title: str | None, **_: object) -> TaxonomyClassificationResult:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.random.uniform(0, 0.02))
        self.in_flight -= 1
        number = int((title or "0").split()[-1])
        return TaxonomyClassificationResult(
            domain=("calidad", "seguridad", None)[number % 3],
            domain_confidence=0.7,
            material_type=("politica", "manual")[number % 2],
            material_type_confidence=0.6,
        )


class _SlowEnrichment:
    config = SimpleNamespace(model="stub-enrich")

    def __init__(self, seed: int) -> None:
        self.random = random.Random(seed)

    async def enrich(self, *, title: str | None, **_: object) -> DocumentEnrichmentResult:
        await asyncio.sleep(self.random.uniform(0, 0.02))
        return DocumentEnrichmentResult(description=f"Sobre {title}", keywords=["uno", (title or "").split()[-1]])


def _saved_context(root: Path) -> dict:
    """El contexto tal como queda en disco, sin las fechas."""
    context = json.loads((root / "context.json").read_text(encoding="utf-8"))
    for key in ("created_at", "updated_at"):
        context.pop(key)
    indexes = {path.parent.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted((root / "domains").glob("*/index.json"))}
    return {"context": context, "indexes": indexes}


@pytest.mark.asyncio
async def test_parallel_ai_gives_the_same_context_as_serial(tmp_path) -> None:
    results = {}
    for concurrency in (1, 4):
        root = tmp_path / f"raiz-concurrencia-{concurrency}"
        documents = _documents(root, 12)
        client = _SlowTaxonomyAI(seed=concurrency)  # latencias distintas en cada ejecución
        await ContextBuilder(ai_concurrency=concurrency).build(
            _project(root),
            documents,
            taxonomy_manifest=_manifest(),
            ai_classification_enabled=True,
            taxonomy_classification_client=client,
            ai_enrichment_enabled=True,
            ai_enrichment_client=_SlowEnrichment(seed=concurrency + 10),
        )
        results[concurrency] = _saved_context(root)
        assert client.max_in_flight <= concurrency
        if concurrency == 4:
            assert client.max_in_flight > 1  # de verdad hubo llamadas a la vez

    serial, parallel = results[1], results[4]
    assert serial["indexes"].keys() == parallel["indexes"].keys()
    for slug in serial["indexes"]:
        # Las rutas cambian de raíz; lo demás tiene que ser idéntico, incluido el orden.
        assert json.dumps(serial["indexes"][slug]).replace("raiz-concurrencia-1", "R") == json.dumps(parallel["indexes"][slug]).replace(
            "raiz-concurrencia-4", "R"
        )
    assert json.dumps(serial["context"]).replace("raiz-concurrencia-1", "R") == json.dumps(parallel["context"]).replace("raiz-concurrencia-4", "R")


class _CountingDomainAI:
    config = SimpleNamespace(model="stub")

    def __init__(self) -> None:
        self.titles: list[str] = []

    async def classify(self, *, title: str | None, **_: object) -> DomainClassificationResult:
        self.titles.append(title or "")
        await asyncio.sleep(0.005 * (5 - len(self.titles) % 5))
        return DomainClassificationResult(domain="calidad", confidence=0.9)


@pytest.mark.asyncio
async def test_budget_is_never_exceeded_and_goes_to_the_first_documents(tmp_path) -> None:
    documents = _documents(tmp_path, 10)
    client = _CountingDomainAI()

    context = await ContextBuilder(ai_concurrency=4).build(
        _project(tmp_path),
        documents,
        candidate_domains=["calidad"],
        ai_classification_enabled=True,
        ai_classification_client=client,
        ai_max_documents=3,
    )

    assert sorted(client.titles) == ["Documento 0", "Documento 1", "Documento 2"]
    assert (context.ai_documents_sent, context.ai_classification_stopped) == (3, "budget")
    assert [document.source_path for document in context.domains[0].documents] == [document.source_path for document in documents[:3]]


@pytest.mark.asyncio
async def test_progress_is_monotonic_and_cancellation_stops_with_calls_in_flight(tmp_path) -> None:
    documents = _documents(tmp_path, 8)
    token = CancelToken()
    seen: list[int] = []

    async def on_ai_progress(index: int, total: int, _path: str) -> None:
        seen.append(index)
        if index == 3:
            token.cancel()

    with pytest.raises(OperationCancelledError):
        await ContextBuilder(ai_concurrency=4).build(
            _project(tmp_path),
            documents,
            taxonomy_manifest=_manifest(),
            ai_classification_enabled=True,
            taxonomy_classification_client=_SlowTaxonomyAI(seed=3),
            on_ai_progress=on_ai_progress,
            cancel_token=token,
        )

    assert seen == sorted(seen) and seen[:3] == [1, 2, 3]
    assert not (tmp_path / "context.json").exists()  # nunca un contexto a medias


def test_ai_concurrency_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="ai_concurrency"):
        ContextBuilder(ai_concurrency=0)
