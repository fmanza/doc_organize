"""Matriz de combinaciones de 2.0 (M10, U7): las opciones nuevas juntas, con invariantes que deben cumplirse siempre.

Combinaciones: sin IA; `ai_scope="unclassified"`; y `missing_axes` + semántica + decisiones + `versions="current_only"`,
seguida del sitio sin conexión con `llms.txt`, el paquete para IA y una reconstrucción sin cambios (cero llamadas).
"""

import io
import json
import zipfile

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.decisions import ClassificationDecisionStore
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.models import ClassificationDecision, Context, ConversionResult, Project
from doc_organize.export.ai_bundle import write_ai_context_bundle
from tests.unit.fake_llm import FakeLlmClient, FakeRequest, fake_client
from tests.unit.test_semantic import _embedder, _manifest

DOCUMENTS = {
    "Calidad/Manual_v1.pdf": "Procedimiento de calidad, versión antigua, con sus pasos.",
    "Calidad/Manual_v2.pdf": "Procedimiento de calidad, versión vigente, con sus pasos.",
    "Varios/auditoria.pdf": "Este documento explica como se hacen las auditorias de los procesos internos y la mejora.",
    "Varios/red.pdf": "Configuracion de la red y del cifrado de las comunicaciones del centro.",
    "Varios/acta.pdf": "Acta de la reunion del comite del dia de hoy, sin mas.",
}
ORGANIZING = ("domains", "material_types")


def _setup(tmp_path: Path) -> tuple[Project, list[ConversionResult]]:
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    documents = []
    for index, (relative, text) in enumerate(DOCUMENTS.items()):
        source = tmp_path / "entrada" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(text.encode())
        (tmp_path / f"d{index}.json").write_text(json.dumps({"title": source.stem, "chunks": [{"text": text}]}), encoding="utf-8")
        (tmp_path / f"d{index}.md").write_text(f"# {source.stem}\n\n{text}\n", encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(source),
                markdown_path=str(tmp_path / f"d{index}.md"),
                json_path=str(tmp_path / f"d{index}.json"),
                success=True,
                source_sha256=f"{index:064x}",
            )
        )
    return project, documents


def _classify(request: FakeRequest) -> dict[str, Any]:
    answers = {"domains": ("seguridad", 0.9), "material_types": ("normativa", 0.9), "topics": [("redes", 0.9)]}
    return {axis: answers.get(axis) for axis in request.axes}


def _llm() -> FakeLlmClient:
    return fake_client(classify=_classify, embed=_embedder())


def _documents(context: Context) -> dict[str, Any]:
    return {Path(document.source_path).name: document for domain in context.domains for document in domain.documents}


def _check_invariants(context: Context) -> None:
    """Lo que debe cumplirse con cualquier combinación de opciones."""
    catalog = {axis.key: {entry.slug for entry in axis.entries} for axis in context.taxonomy_axes}
    for domain in context.domains:
        for document in domain.documents:
            for axis, values in document.classification.axes.items():
                assert {value.slug for value in values} <= catalog[axis], (document.source_path, axis)
                assert all(value.classified_by in {"rules", "semantic", "ai", "human"} for value in values)
                if axis in ORGANIZING:
                    assert len(values) <= 1, (document.source_path, axis)
            domain_values = document.classification.axes.get("domains", [])
            assert not domain_values or domain_values[0].slug == domain.slug  # la carpeta es el valor del eje


@pytest.mark.asyncio
async def test_without_ai(tmp_path) -> None:
    project, documents = _setup(tmp_path)

    context = await ContextBuilder().build(project, documents, taxonomy_manifest=_manifest(), persist=False)

    _check_invariants(context)
    used = {value.classified_by for document in _documents(context).values() for values in document.classification.axes.values() for value in values}
    assert used <= {"rules"} and context.ai_stats.scope == "off" and not context.superseded_documents


@pytest.mark.asyncio
async def test_ai_only_for_the_unclassified(tmp_path) -> None:
    project, documents = _setup(tmp_path)
    llm = _llm()

    context = await ContextBuilder().build(
        project, documents, taxonomy_manifest=_manifest(), llm=llm, ai_scope="unclassified", ai_cache=False, persist=False
    )

    _check_invariants(context)
    by_name = _documents(context)
    assert by_name["Manual_v2.pdf"].classification.axes["domains"][0].classified_by == "rules"  # la IA no toca lo resuelto
    sent = context.ai_stats.classification.sent
    assert sent == len(llm.proxy.calls("classify")) and sent >= 1 and not llm.proxy.calls("embed")
    assert all(
        value.classified_by != "semantic" for document in by_name.values() for values in document.classification.axes.values() for value in values
    )


@pytest.mark.asyncio
async def test_everything_together(tmp_path) -> None:
    project, documents = _setup(tmp_path)
    await ClassificationDecisionStore(tmp_path).add(
        ClassificationDecision(document_key="Varios/red.pdf", action="set_axis", axes={"domains": ["calidad"]}, reason="decidido")
    )
    options: dict[str, Any] = {
        "taxonomy_manifest": _manifest(),
        "ai_scope": "missing_axes",
        "semantic": True,
        "semantic_threshold": 0.6,
        "versions": "current_only",
        "scan_roots": [str(tmp_path / "entrada")],
    }
    llm = _llm()

    context = await ContextBuilder().build(project, documents, llm=llm, **options)

    _check_invariants(context)
    by_name = _documents(context)
    # versiones: la antigua no entra
    assert "Manual_v1.pdf" not in by_name and [Path(path).name for path in context.superseded_documents] == ["Manual_v1.pdf"]
    # decisión de una persona: gana a reglas, semántica e IA
    assert [(value.slug, value.classified_by) for value in by_name["red.pdf"].classification.axes["domains"]] == [("calidad", "human")]
    assert context.decisions_applied == 1
    # semántica antes que la IA
    assert by_name["auditoria.pdf"].classification.axes["domains"][0].classified_by == "semantic"
    assert context.ai_stats.semantic and context.ai_stats.semantic_classification.assigned >= 1
    # la IA solo para lo que sigue vacío
    sent = context.ai_stats.classification.sent
    assert sent == len(llm.proxy.calls("classify")) and sent >= 1
    assert by_name["acta.pdf"].classification.axes["domains"][0].classified_by == "ai"  # ni reglas ni semántica: la IA
    assert by_name["Manual_v2.pdf"].classification.axes["domains"][0].classified_by == "rules"
    used = {value.classified_by for document in by_name.values() for values in document.classification.axes.values() for value in values}
    assert used == {"rules", "semantic", "ai", "human"}  # los cuatro mecanismos en una construcción

    # sitio sin conexión con llms.txt y paquete para IA, sobre el mismo contexto
    await Reorganizer().reorganize(project, context)
    site = await SiteGenerator().generate(project, context, build=False, offline=True, llms_txt=True)
    llms = (tmp_path / "organizado" / "llms.txt").read_text(encoding="utf-8")
    assert site.offline and "Manual_v1" not in llms and ".html)" in llms
    buffer = io.BytesIO()
    bundle = write_ai_context_bundle(buffer, project, context)
    with zipfile.ZipFile(buffer) as archive:
        names = archive.namelist()
    assert bundle.documents == len(by_name) and not any("Manual_v1" in name for name in names)

    # reconstruir sin cambios: ninguna llamada nueva (caché de IA e índice de embeddings)
    again = _llm()
    rebuilt = await ContextBuilder().build(project, documents, llm=again, **options)

    _check_invariants(rebuilt)
    assert again.proxy.calls("classify") == [] and again.proxy.calls("embed") == []
    assert {name: document.classification.axes for name, document in _documents(rebuilt).items()} == {
        name: document.classification.axes for name, document in by_name.items()
    }
