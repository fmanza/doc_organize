"""Ejemplos recuperados y preselección para la IA (M7, G4): solo documentos fiables, nunca el propio documento, sus
duplicados ni la referencia al evaluar (B16, puerta de M7)."""

import json

from datetime import UTC, datetime

import pytest

from doc_organize import ClassificationDecision, ContextBuilder, GoldLabel, GoldStandard, dry_run_classify
from doc_organize.context.semantic import PRESELECT_TOP
from doc_organize.core.models import ConversionResult, Project, TaxonomyEntry
from doc_organize.utils.folding import fold
from tests.unit.fake_llm import FakeRequest, fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

VOCABULARY = ("auditor", "proceso", "red", "cifrado")
TEXT = "Documento para preparar las auditorias de los procesos internos y revisar la red del equipo."


def _vector(text: str) -> list[float]:
    folded = fold(text)
    return [float(folded.count(root)) for root in VOCABULARY] + [0.01]


def _embed(request: FakeRequest) -> list[list[float]]:
    return [_vector(text) for text in request.body["input"]]


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, stem: str, text: str = TEXT, sha: str | None = None) -> ConversionResult:
    (tmp_path / "entrada").mkdir(exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": f"Titulo {stem}", "chunks": [{"text": text}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
    return ConversionResult(
        source_path=str(tmp_path / "entrada" / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md"),
        json_path=str(json_path),
        success=True,
        source_sha256=sha or f"sha-{stem}",
    )


def _manifest(domains: int = 2):
    entries = [
        TaxonomyEntry(slug="calidad", name="Calidad", description="Auditorias de procesos"),
        TaxonomyEntry(slug="seguridad", name="Seguridad", description="Red y cifrado"),
    ]
    entries += [TaxonomyEntry(slug=f"otro-{n}", name=f"Otro {n}", description="cifrado" if n % 2 else "red") for n in range(domains - 2)]
    return two_axis_manifest(entries, [TaxonomyEntry(slug="manual", name="Manual"), TaxonomyEntry(slug="guia", name="Guia")])


def _confirm(stem: str) -> ClassificationDecision:
    return ClassificationDecision(document_key=f"{stem}.pdf", action="confirm", axes={"domains": ["calidad"], "material_types": ["manual"]})


def _requests_by_title(llm) -> dict[str, FakeRequest]:
    return {request.title: request for request in llm.proxy.calls("classify")}


@pytest.mark.asyncio
async def test_examples_come_from_trusted_documents_and_never_from_itself_its_duplicates_or_the_reference(tmp_path) -> None:
    documents = [
        _document(tmp_path, "objetivo", sha="sha-x"),
        _document(tmp_path, "fiable"),  # decidido por una persona: sirve de ejemplo
        _document(tmp_path, "duplicado", sha="sha-x"),  # mismo original que el objetivo: nunca
        _document(tmp_path, "referencia"),  # en la referencia de la evaluación: nunca
        _document(tmp_path, "dudoso"),  # lo clasificó la IA sin fiabilidad: no es ejemplo
    ]
    llm = fake_client(embed=_embed, classify=lambda request: {request.axes[0]: ("calidad", 0.6)})

    await ContextBuilder().build(
        _project(tmp_path),
        documents,
        taxonomy_manifest=_manifest(),
        llm=llm,
        ai_scope="unclassified",
        semantic=True,
        semantic_threshold=0.9,  # que la semántica no asigne (similitud ~0,82): todo va a la IA
        decisions=[_confirm("fiable"), _confirm("duplicado"), _confirm("referencia")],
        example_exclusions=["referencia.pdf"],
        scan_roots=[str(tmp_path / "entrada")],
        ai_cache=False,
    )

    requests = _requests_by_title(llm)
    user = requests["Titulo objetivo"].body["messages"][-1]["content"]
    assert "Documentos parecidos ya clasificados (orientativo):\n- «Titulo fiable» → domains: calidad; material_types: manual" in user
    for leaked in ("Titulo objetivo»", "Titulo duplicado", "Titulo referencia", "Titulo dudoso"):
        assert leaked not in user.split("<<<DOCUMENTO")[0]
    systems = {request.body["messages"][0]["content"] for request in requests.values()}
    assert len(systems) == 1  # el prefijo `system` no cambia entre documentos


@pytest.mark.asyncio
async def test_big_axes_send_only_the_closest_values(tmp_path) -> None:
    llm = fake_client(embed=_embed, classify=lambda request: {request.axes[0]: "calidad"})

    await ContextBuilder().build(
        _project(tmp_path),
        [_document(tmp_path, "objetivo")],
        taxonomy_manifest=_manifest(domains=30),
        llm=llm,
        ai_scope="unclassified",
        semantic=True,
        semantic_threshold=0.9,
        ai_cache=False,
    )

    [request] = llm.proxy.calls("classify")
    schema = request.body["response_format"]["json_schema"]["schema"]["properties"]
    domains = schema["domains"]["properties"]["values"]["items"]["properties"]["value"]["enum"]
    materials = schema["material_types"]["properties"]["values"]["items"]["properties"]["value"]["enum"]
    assert len(domains) == PRESELECT_TOP and domains[0] == "calidad"  # el más parecido, y en el orden del catálogo
    assert materials == ["manual", "guia"]  # un eje pequeño va entero


@pytest.mark.asyncio
async def test_without_semantic_there_are_no_examples(tmp_path) -> None:
    llm = fake_client(classify=lambda request: {request.axes[0]: "calidad"})

    await ContextBuilder().build(
        _project(tmp_path),
        [_document(tmp_path, "objetivo"), _document(tmp_path, "fiable")],
        taxonomy_manifest=_manifest(),
        llm=llm,
        ai_scope="unclassified",
        decisions=[_confirm("fiable")],
        ai_cache=False,
    )

    assert all("Documentos parecidos" not in request.text for request in llm.proxy.calls("classify"))


@pytest.mark.asyncio
async def test_dry_run_never_uses_the_reference_as_examples(tmp_path) -> None:
    documents = [_document(tmp_path, "objetivo"), _document(tmp_path, "referencia")]
    gold = GoldStandard(
        labels=[
            GoldLabel(document="objetivo.pdf", axes={"domains": ["calidad"]}),
            GoldLabel(document="referencia.pdf", axes={"domains": ["calidad"]}),
        ]
    )
    llm = fake_client(embed=_embed, classify=lambda request: {request.axes[0]: "calidad"})

    await dry_run_classify(
        _project(tmp_path),
        documents,
        gold=gold,
        only_gold=False,
        taxonomy_manifest=_manifest(),
        llm=llm,
        ai_scope="unclassified",
        semantic=True,
        semantic_threshold=0.9,
        decisions=[_confirm("referencia")],
    )

    assert all("Titulo referencia" not in request.text.split("<<<DOCUMENTO")[0] for request in llm.proxy.calls("classify"))
