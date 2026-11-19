"""Clasificación de prueba (M6, G3): sin guardar nada, solo los documentos de la referencia, evaluada, y para comparar
dos configuraciones."""

import json

from datetime import UTC, datetime

import pytest

from doc_organize import ContextRegistry, GoldLabel, GoldStandard, PromptRegistry, dry_run_classify
from doc_organize.core.exceptions import ContextNotFoundError
from doc_organize.core.models import ConversionResult, Project, TaxonomyEntry
from doc_organize.projects.layout import ProjectLayout
from tests.unit.fake_llm import fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

TEXT = "Texto del documento con suficiente contenido para que cuente como texto de verdad en el extracto."


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, folder: str, stem: str) -> ConversionResult:
    (tmp_path / "entrada" / folder).mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": stem, "chunks": [{"text": TEXT}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
    return ConversionResult(
        source_path=str(tmp_path / "entrada" / folder / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md"),
        json_path=str(json_path),
        success=True,
    )


def _manifest():
    return two_axis_manifest(
        [TaxonomyEntry(slug="calidad", name="Calidad"), TaxonomyEntry(slug="seguridad", name="Seguridad")],
        [TaxonomyEntry(slug="manual", name="Manual"), TaxonomyEntry(slug="politica", name="Política")],
    )


@pytest.mark.asyncio
async def test_dry_run_saves_nothing_classifies_only_the_reference_and_evaluates(tmp_path) -> None:
    documents = [_document(tmp_path, "A", "uno"), _document(tmp_path, "A", "dos"), _document(tmp_path, "B", "tres")]
    gold = GoldStandard(
        labels=[GoldLabel(document="A/uno.pdf", axes={"domains": ["seguridad"]}), GoldLabel(document="A/dos.pdf", axes={"domains": ["calidad"]})]
    )
    llm = fake_client(classify=lambda request: {request.axes[0]: "seguridad", request.axes[1]: "manual"})

    result = await dry_run_classify(_project(tmp_path), documents, gold=gold, taxonomy_manifest=_manifest(), llm=llm, ai_scope="unclassified")

    assert result.documents == 2  # «tres» no está en la referencia: no se clasifica ni gasta llamadas
    assert len(llm.proxy.calls("classify")) == 2
    assert result.evaluation is not None
    assert (result.evaluation.matched, result.evaluation.axes["domains"].accuracy) == (2, 0.5)
    assert result.context.ai_stats.classification.sent == 2
    with pytest.raises(ContextNotFoundError):
        await ContextRegistry().load_context(_project(tmp_path))
    layout = ProjectLayout.for_project(_project(tmp_path))
    assert not layout.context_history.exists()
    assert not (tmp_path / ".doc_organize" / "ai_cache").exists()


@pytest.mark.asyncio
async def test_dry_run_compares_two_prompts_with_real_calls(tmp_path) -> None:
    documents = [_document(tmp_path, "A", "uno"), _document(tmp_path, "B", "dos")]
    gold = GoldStandard(
        labels=[GoldLabel(document="A/uno.pdf", axes={"domains": ["seguridad"]}), GoldLabel(document="B/dos.pdf", axes={"domains": ["seguridad"]})]
    )
    folder = tmp_path / "otro_prompt"
    (folder / ".doc_organize" / "prompts").mkdir(parents=True)
    builtin = PromptRegistry().get("classify")
    (folder / ".doc_organize" / "prompts" / "classify.md").write_text(
        f"---\nid: classify-b\nversion: 1\n---\n## system\nVARIANTE B\n{builtin.system.template}\n## user\n{builtin.user.template}\n",
        encoding="utf-8",
    )

    def respond(request):
        domain = "seguridad" if "VARIANTE B" in request.text else "calidad"
        return {request.axes[0]: domain, request.axes[1]: "manual"}

    options = {"gold": gold, "taxonomy_manifest": _manifest(), "llm": fake_client(classify=respond), "ai_scope": "unclassified"}
    base = await dry_run_classify(_project(tmp_path), documents, **options)
    variant = await dry_run_classify(_project(tmp_path), documents, prompts=PromptRegistry(folder), **options)

    assert base.evaluation is not None and variant.evaluation is not None
    assert (base.evaluation.axes["domains"].accuracy, variant.evaluation.axes["domains"].accuracy) == (0.0, 1.0)
    assert [p.prompt_id for p in variant.context.ai_provenance] == ["classify-b"]


@pytest.mark.asyncio
async def test_dry_run_without_reference_classifies_everything_and_refuses_persist(tmp_path) -> None:
    documents = [_document(tmp_path, "A", "uno"), _document(tmp_path, "B", "dos")]

    result = await dry_run_classify(_project(tmp_path), documents, taxonomy_manifest=_manifest())

    assert (result.documents, result.evaluation) == (2, None)
    with pytest.raises(TypeError, match="persist"):
        await dry_run_classify(_project(tmp_path), documents, persist=True)
