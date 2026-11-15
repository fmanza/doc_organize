"""Autor, descripción y palabras clave de cada DomainDocument (1.5.0): lo declarado en el documento y, con opt-in, la IA.

La IA se sustituye por un doble con guion (sin red); el cliente real se prueba en `test_document_enrichment_client.py`.
"""

import json
import zipfile

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.core.exceptions import DocumentEnrichmentAuthError, DocumentEnrichmentConnectionError
from doc_organize.core.models import Context, ConversionResult, DocumentEnrichmentResult, DomainDocument, Project
from doc_organize.core.progress import ProgressEvent
from tests.unit.test_document_properties import core_xml, make_pdf
from tests.unit.test_language_detection import SPANISH


def _project(tmp_path: Path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path: Path, name: str, content: bytes | None = None) -> ConversionResult:
    """Documento convertido de la carpeta `Calidad/` (la Sub-fase A lo clasifica en el dominio `calidad`)."""
    source = tmp_path / "Calidad" / name
    source.parent.mkdir(exist_ok=True)
    if content is not None:
        source.write_bytes(content)
    stem = source.stem
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": stem, "chunks": [{"text": f"contenido de {stem}"}]}), encoding="utf-8")
    markdown_path = tmp_path / f"{stem}.md"
    markdown_path.write_text(f"# {stem}", encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown_path), json_path=str(json_path), success=True)


def _docx(tmp_path: Path, name: str, **properties: str) -> bytes:
    path = tmp_path / f"_{name}"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("docProps/core.xml", core_xml(**properties))
    return path.read_bytes()


def _by_name(context: Context) -> dict[str, DomainDocument]:
    return {Path(document.source_path).name: document for domain in context.domains for document in domain.documents}


class _ScriptedEnrichment:
    """Doble de `DocumentEnrichmentClient`: `"ok"` propone descripción y palabras clave; `"auth"`/`"conn"` fallan."""

    config = SimpleNamespace(model="stub-enricher")

    def __init__(self, script: list[str] | None = None) -> None:
        self.script = list(script or [])
        self.titles: list[str | None] = []

    async def enrich(self, *, chunks_text: str, title: str | None) -> DocumentEnrichmentResult:
        outcome = self.script[len(self.titles)] if len(self.titles) < len(self.script) else "ok"
        self.titles.append(title)
        if outcome == "auth":
            raise DocumentEnrichmentAuthError("clave rechazada")
        if outcome == "conn":
            raise DocumentEnrichmentConnectionError("sin red")
        return DocumentEnrichmentResult(description=f"Resumen de {title}", keywords=["ia"])


async def _build(tmp_path: Path, documents: list[ConversionResult], **kwargs: object) -> Context:
    return await ContextBuilder(ContextRegistry()).build(_project(tmp_path), documents, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_declared_properties_are_applied_without_ai(tmp_path: Path) -> None:
    documents = [
        _document(tmp_path, "informe.pdf", make_pdf("<</Author(Ana Ruiz)/Subject(Informe anual)/Keywords(calidad; ISO 9001)>>")),
        _document(tmp_path, "plan.docx", _docx(tmp_path, "plan.docx", creator="Luis Gil", description="Plan", keywords="auditoría")),
        _document(tmp_path, "borrado.pdf"),  # el original ya no existe
    ]

    context = await _build(tmp_path, documents)

    docs = _by_name(context)
    assert (docs["informe.pdf"].author, docs["informe.pdf"].description, docs["informe.pdf"].keywords) == (
        "Ana Ruiz",
        "Informe anual",
        ["calidad", "ISO 9001"],
    )
    assert (docs["plan.docx"].author, docs["plan.docx"].keywords) == ("Luis Gil", ["auditoría"])
    assert (docs["borrado.pdf"].author, docs["borrado.pdf"].description, docs["borrado.pdf"].keywords) == (None, None, [])
    assert all(not doc.ai_filled for doc in docs.values())
    assert context.ai_enrichment_enabled is False
    assert context.ai_enrichment_sent == 0


@pytest.mark.asyncio
async def test_ai_fills_only_what_the_document_does_not_declare(tmp_path: Path) -> None:
    documents = [
        _document(tmp_path, "completo.pdf", make_pdf("<</Author(Ana)/Subject(Declarada)/Keywords(propia)>>")),
        _document(tmp_path, "sin-claves.pdf", make_pdf("<</Author(Ana)/Subject(Declarada)>>")),
        _document(tmp_path, "vacio.pdf", make_pdf(None)),
    ]
    client = _ScriptedEnrichment()

    context = await _build(tmp_path, documents, ai_enrichment_enabled=True, ai_enrichment_client=client)

    docs = _by_name(context)
    assert sorted(client.titles) == ["sin-claves", "vacio"]  # el documento completo no se envía
    assert (docs["completo.pdf"].description, docs["completo.pdf"].keywords, docs["completo.pdf"].ai_filled) == ("Declarada", ["propia"], [])
    assert (docs["sin-claves.pdf"].description, docs["sin-claves.pdf"].keywords) == ("Declarada", ["ia"])
    assert docs["sin-claves.pdf"].ai_filled == ["keywords"]
    assert (docs["vacio.pdf"].description, docs["vacio.pdf"].ai_filled) == ("Resumen de vacio", ["description", "keywords"])
    assert docs["vacio.pdf"].author is None  # el autor nunca sale de la IA
    assert (context.ai_enrichment_enabled, context.ai_enrichment_sent, context.ai_enrichment_applied) == (True, 2, 2)

    reloaded = _by_name(await ContextRegistry().load_context(_project(tmp_path)))
    assert reloaded["vacio.pdf"].model_dump() == docs["vacio.pdf"].model_dump()


@pytest.mark.asyncio
async def test_language_is_detected_from_the_converted_text(tmp_path: Path) -> None:
    spanish = _document(tmp_path, "procedimiento.pdf")
    Path(spanish.json_path).write_text(  # type: ignore[arg-type]
        json.dumps({"title": "Auditoría", "chunks": [{"text": SPANISH}]}),
        encoding="utf-8",
    )
    short = _document(tmp_path, "corto.pdf")  # «contenido de corto»: demasiado poco texto

    docs = _by_name(await _build(tmp_path, [spanish, short]))

    assert docs["procedimiento.pdf"].language == "es"
    assert docs["corto.pdf"].language is None


@pytest.mark.asyncio
async def test_enrichment_needs_the_opt_in(tmp_path: Path) -> None:
    client = _ScriptedEnrichment()
    context = await _build(tmp_path, [_document(tmp_path, "vacio.pdf", make_pdf(None))], ai_enrichment_client=client)
    assert client.titles == []
    assert _by_name(context)["vacio.pdf"].description is None


@pytest.mark.asyncio
async def test_rejected_key_stops_enrichment_after_one_call(tmp_path: Path) -> None:
    documents = [_document(tmp_path, f"d{i}.pdf", make_pdf(None)) for i in range(3)]
    client = _ScriptedEnrichment(["auth"])

    context = await _build(tmp_path, documents, ai_enrichment_enabled=True, ai_enrichment_client=client)

    assert len(client.titles) == 1
    assert (context.ai_enrichment_stopped, context.ai_enrichment_sent, context.ai_enrichment_failed) == ("auth", 1, 1)
    assert all(doc.description is None for doc in _by_name(context).values())


@pytest.mark.asyncio
async def test_enrichment_has_its_own_budget_and_connection_limit(tmp_path: Path) -> None:
    documents = [_document(tmp_path, f"d{i}.pdf", make_pdf(None)) for i in range(3)]

    budget = await _build(tmp_path, documents, ai_enrichment_enabled=True, ai_enrichment_client=_ScriptedEnrichment(), ai_max_documents=1)
    assert (budget.ai_enrichment_stopped, budget.ai_enrichment_sent, budget.ai_enrichment_applied) == ("budget", 1, 1)

    client = _ScriptedEnrichment(["conn", "conn", "ok"])
    failing = await _build(tmp_path, documents, ai_enrichment_enabled=True, ai_enrichment_client=client, ai_max_failures=2)
    assert len(client.titles) == 2
    assert (failing.ai_enrichment_stopped, failing.ai_enrichment_failed) == ("connection", 2)


@pytest.mark.asyncio
async def test_enrichment_reports_its_own_progress_phase(tmp_path: Path) -> None:
    documents = [_document(tmp_path, f"d{i}.pdf", make_pdf(None)) for i in range(2)]
    events: list[ProgressEvent] = []

    await _build(tmp_path, documents, ai_enrichment_enabled=True, ai_enrichment_client=_ScriptedEnrichment(), on_progress=events.append)

    assert [(event.phase, event.processed, event.total) for event in events] == [("enrichment", 1, 2), ("enrichment", 2, 2)]
