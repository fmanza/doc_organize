"""Metadatos de los documentos sin clasificar y su persistencia en `unclassified.json` (G42, 1.6.0)."""

import asyncio
import json
import logging

from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_organize.context import context_builder as context_builder_module
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.core.exceptions import ContextError
from doc_organize.core.models import (
    Context,
    ConversionResult,
    DomainClassificationResult,
    Project,
    TaxonomyCatalogEntry,
    TaxonomyManifest,
    UnclassifiedDocument,
)
from doc_organize.projects.layout import RESERVED_OUTPUT_FOLDER_NAMES, ProjectLayout
from tests.unit.test_context_builder_enrichment import _document, _project, _ScriptedEnrichment
from tests.unit.test_document_properties import make_pdf
from tests.unit.test_language_detection import SPANISH

_CATALOG = ["ciberseguridad"]


def _converted(tmp_path: Path, folder: str, name: str, *, text: str, content: bytes | None = None) -> ConversionResult:
    """Documento convertido en `<folder>/<name>` cuyo `.json` lleva `text` como único fragmento."""
    source = tmp_path / folder / name
    source.parent.mkdir(exist_ok=True)
    if content is not None:
        source.write_bytes(content)
    json_path = tmp_path / f"{source.stem}.json"
    json_path.write_text(json.dumps({"title": source.stem, "chunks": [{"text": text}]}), encoding="utf-8")
    markdown_path = tmp_path / f"{source.stem}.md"
    markdown_path.write_text(f"# {source.stem}", encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown_path), json_path=str(json_path), success=True)


def _failed(tmp_path: Path, name: str) -> ConversionResult:
    source = tmp_path / "Calidad" / name
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(make_pdf("<</Author(Eva Sanz)>>"))
    return ConversionResult(source_path=str(source), success=False, error="Docling falló")


def _mixed(tmp_path: Path) -> list[ConversionResult]:
    return [
        _converted(tmp_path, "Seguridad", "politica.pdf", text="ciberseguridad ciberseguridad", content=make_pdf(None)),
        _converted(
            tmp_path,
            "Calidad",
            "auditorias.pdf",
            text=SPANISH,
            content=make_pdf("<</Author(Ana Ruiz)/Subject(Auditorías internas)/Keywords(calidad; ISO 9001)>>"),
        ),
        _failed(tmp_path, "escaneado.pdf"),
    ]


async def _build(tmp_path: Path, documents: list[ConversionResult], **kwargs: object) -> Context:
    return await ContextBuilder(ContextRegistry()).build(_project(tmp_path), documents, candidate_domains=_CATALOG, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_each_unclassified_document_gets_its_reason_and_metadata(tmp_path: Path) -> None:
    context = await _build(tmp_path, _mixed(tmp_path))

    assert [Path(path).name for path in context.unclassified_documents] == ["auditorias.pdf", "escaneado.pdf"]
    below, incomplete = context.unclassified_details
    assert [detail.source_path for detail in context.unclassified_details] == context.unclassified_documents
    assert below.reason == "below_threshold"
    assert (below.title, below.document_type, below.language) == ("auditorias", "pdf", "es")
    assert (below.author, below.description, below.keywords) == ("Ana Ruiz", "Auditorías internas", ["calidad", "ISO 9001"])
    assert below.markdown_path is not None and below.json_path is not None
    assert (below.rules_domain is None) == (below.rules_confidence is None)
    assert incomplete.reason == "incomplete_artifacts"
    assert (incomplete.title, incomplete.document_type, incomplete.language) == (None, "pdf", None)
    assert (incomplete.markdown_path, incomplete.json_path) == (None, None)
    assert incomplete.author == "Eva Sanz"  # el original sí se lee aunque la conversión fallara


@pytest.mark.asyncio
async def test_unreadable_json_is_incomplete_and_a_deleted_original_has_no_properties(tmp_path: Path) -> None:
    damaged = _converted(tmp_path, "Calidad", "danado.pdf", text="x")
    Path(damaged.json_path or "").write_text("{no es json", encoding="utf-8")
    deleted = _converted(tmp_path, "Calidad", "borrado.docx", text=SPANISH)  # sin original en disco

    context = await _build(tmp_path, [damaged, deleted])

    by_name = {Path(detail.source_path).name: detail for detail in context.unclassified_details}
    assert by_name["danado.pdf"].reason == "incomplete_artifacts"
    assert by_name["danado.pdf"].title == "danado"  # nombre del .md
    assert by_name["borrado.docx"].reason == "below_threshold"
    assert (by_name["borrado.docx"].author, by_name["borrado.docx"].keywords) == (None, [])


@pytest.mark.asyncio
async def test_rules_proposal_below_the_threshold_is_kept(tmp_path: Path) -> None:
    weak = _converted(tmp_path, "Varios", "nota.pdf", text="habla de seguridad, pero de nada informático")  # 1 de 2 palabras

    context = await ContextBuilder(ContextRegistry()).build(_project(tmp_path), [weak], candidate_domains=["seguridad-informatica"], threshold=0.6)

    (detail,) = context.unclassified_details
    assert (detail.reason, detail.rules_domain, detail.rules_confidence) == ("below_threshold", "seguridad-informatica", 0.5)


@pytest.mark.asyncio
async def test_ai_enrichment_never_describes_unclassified_documents(tmp_path: Path) -> None:
    client = _ScriptedEnrichment()
    documents = _mixed(tmp_path)
    documents.append(_converted(tmp_path, "Calidad", "sin_propiedades.pdf", text=SPANISH, content=make_pdf(None)))

    context = await _build(tmp_path, documents, ai_enrichment_enabled=True, ai_enrichment_client=client)

    assert client.titles == ["politica"]  # solo el clasificado
    by_name = {Path(detail.source_path).name: detail for detail in context.unclassified_details}
    assert (by_name["sin_propiedades.pdf"].description, by_name["sin_propiedades.pdf"].keywords) == (None, [])


@pytest.mark.asyncio
async def test_details_are_saved_apart_and_reloaded(tmp_path: Path) -> None:
    project = _project(tmp_path)
    built = await ContextBuilder(ContextRegistry()).build(project, _mixed(tmp_path), candidate_domains=_CATALOG)
    layout = ProjectLayout.for_project(project)

    stored = json.loads(layout.context_file.read_text(encoding="utf-8"))
    loaded = await ContextRegistry().load_context(project)

    assert "unclassified_details" not in stored
    assert stored["unclassified_documents"] == built.unclassified_documents
    assert layout.unclassified_file.name == "unclassified.json"
    assert len(json.loads(layout.unclassified_file.read_text(encoding="utf-8"))["documents"]) == 2
    assert loaded.unclassified_details == built.unclassified_details


def _saved_context(project: Project, paths: list[str]) -> Context:
    return Context(
        project_name=project.name,
        unclassified_documents=paths,
        unclassified_details=[UnclassifiedDocument(source_path=path, document_type="pdf", reason="below_threshold") for path in paths],
        created_at="2026-11-16T00:00:00+00:00",
        updated_at="2026-11-16T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_a_context_without_unclassified_json_loads_with_no_details(tmp_path: Path) -> None:
    project = _project(tmp_path)
    await ContextRegistry().save_context(project, _saved_context(project, ["/a.pdf"]))
    ProjectLayout.for_project(project).unclassified_file.unlink()  # contexto guardado por 1.5.0

    loaded = await ContextRegistry().load_context(project)

    assert loaded.unclassified_documents == ["/a.pdf"]
    assert loaded.unclassified_details == []


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["{no es json", "[]", '{"documents": {}}', '{"documents": [{"source_path": "/a.pdf"}]}'])
async def test_a_damaged_unclassified_json_is_a_context_error(tmp_path: Path, content: str) -> None:
    project = _project(tmp_path)
    await ContextRegistry().save_context(project, _saved_context(project, ["/a.pdf"]))
    ProjectLayout.for_project(project).unclassified_file.write_text(content, encoding="utf-8")

    with pytest.raises(ContextError, match="sin clasificar"):
        await ContextRegistry().load_context(project)


@pytest.mark.asyncio
async def test_context_json_decides_which_details_are_kept(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    project = _project(tmp_path)
    registry = ContextRegistry()
    await registry.save_context(project, _saved_context(project, ["/a.pdf", "/b.pdf", "/c.pdf"]))
    context_file = ProjectLayout.for_project(project).context_file
    stored = json.loads(context_file.read_text(encoding="utf-8"))
    stored["unclassified_documents"] = ["/c.pdf", "/nuevo.pdf", "/a.pdf"]  # un consumidor editó el contexto
    context_file.write_text(json.dumps(stored), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loaded = await registry.load_context(project)

    assert [detail.source_path for detail in loaded.unclassified_details] == ["/c.pdf", "/a.pdf"]
    assert "se conservan 2 de 3" in caplog.text


@pytest.mark.asyncio
async def test_a_context_saved_without_details_loads_silently(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    project = _project(tmp_path)
    context = _saved_context(project, ["/a.pdf"])
    context.unclassified_details = []  # `Context` creado a mano, sin detalle

    await ContextRegistry().save_context(project, context)
    with caplog.at_level(logging.WARNING):
        loaded = await ContextRegistry().load_context(project)

    assert loaded.unclassified_details == []
    assert "unclassified" not in caplog.text


@pytest.mark.asyncio
async def test_deleting_the_context_removes_unclassified_json(tmp_path: Path) -> None:
    project = _project(tmp_path)
    await ContextRegistry().save_context(project, _saved_context(project, ["/a.pdf"]))

    await ContextRegistry().delete_context(project)

    assert not ProjectLayout.for_project(project).unclassified_file.exists()


def test_unclassified_json_is_a_reserved_output_folder_name() -> None:
    assert "unclassified.json" in RESERVED_OUTPUT_FOLDER_NAMES


@pytest.mark.asyncio
async def test_classified_documents_are_unchanged(tmp_path: Path) -> None:
    documents = [_document(tmp_path, "informe.pdf", make_pdf("<</Author(Ana Ruiz)>>"))]

    context = await ContextBuilder(ContextRegistry()).build(_project(tmp_path), documents)

    assert context.unclassified_details == []
    assert context.domains[0].documents[0].author == "Ana Ruiz"


class _UndecidedAI:
    """Doble de `DomainClassificationClient` que nunca elige dominio."""

    config = SimpleNamespace(model="modelo-dominios")

    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, *, chunks_text: str, title: str | None, candidate_domains: list[str]) -> DomainClassificationResult:
        self.calls += 1
        return DomainClassificationResult(domain=None, confidence=0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, 0])
async def test_after_the_ai_phase_they_are_still_below_threshold(tmp_path: Path, budget: int | None) -> None:
    """La IA no eligió dominio (`None`) o no llegó a preguntarse (presupuesto 0): el motivo es el mismo."""
    client = _UndecidedAI()
    documents = [_converted(tmp_path, "Calidad", "auditorias.pdf", text=SPANISH)]
    await _build(tmp_path, [_converted(tmp_path, "Seguridad", "politica.pdf", text="ciberseguridad")])  # el catálogo existe

    context = await _build(tmp_path, documents, ai_classification_enabled=True, ai_classification_client=client, ai_max_documents=budget)

    (detail,) = context.unclassified_details
    assert detail.reason == "below_threshold"
    assert client.calls == (1 if budget is None else 0)


@pytest.mark.asyncio
async def test_manifest_mode_only_leaves_incomplete_documents_without_rules_proposal(tmp_path: Path) -> None:
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad")],
        material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento")],
    )
    documents = [_converted(tmp_path, "Varios", "nada.pdf", text="texto sin ninguna palabra del catálogo"), _failed(tmp_path, "roto.pdf")]

    context = await ContextBuilder(ContextRegistry()).build(_project(tmp_path), documents, taxonomy_manifest=manifest)

    (detail,) = context.unclassified_details  # «nada.pdf» va a «sin-clasificar» en el eje, no a la lista
    assert (Path(detail.source_path).name, detail.reason) == ("roto.pdf", "incomplete_artifacts")
    assert (detail.rules_domain, detail.rules_confidence) == (None, None)
    assert detail.author == "Eva Sanz"


@pytest.mark.asyncio
async def test_their_json_files_are_read_with_bounded_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = context_builder_module.read_conversion_json
    active = peak = 0

    async def slow_read(json_path: str) -> tuple[str, str | None] | None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return await real(json_path)

    monkeypatch.setattr(context_builder_module, "read_conversion_json", slow_read)
    documents = [_converted(tmp_path, "Calidad", f"doc{i}.pdf", text=SPANISH) for i in range(10)]

    context = await ContextBuilder(ContextRegistry(), properties_concurrency=3).build(_project(tmp_path), documents, candidate_domains=_CATALOG)

    assert peak == 3
    assert [Path(detail.source_path).name for detail in context.unclassified_details] == [f"doc{i}.pdf" for i in range(10)]
    assert all(detail.language == "es" for detail in context.unclassified_details)


@pytest.mark.asyncio
async def test_get_domain_does_not_read_unclassified_json(tmp_path: Path) -> None:
    project = _project(tmp_path)
    await _build(tmp_path, _mixed(tmp_path))
    ProjectLayout.for_project(project).unclassified_file.write_text("{dañado", encoding="utf-8")

    domain = await ContextRegistry().get_domain(project, "ciberseguridad")

    assert [Path(document.source_path).name for document in domain.documents] == ["politica.pdf"]
    with pytest.raises(ContextError):
        await ContextRegistry().load_context(project)
