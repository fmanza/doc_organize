"""Decisiones de personas (M6, F6): almacén con historial, aplicación tras las reglas y antes de la IA, decisiones
desfasadas y huérfanas, exclusión y referencia a partir de decisiones."""

import json

from datetime import UTC, datetime

import pytest

from pydantic import ValidationError

from doc_organize import (
    ClassificationDecision,
    ClassificationDecisionStore,
    ContextBuilder,
    evaluate_classification,
    gold_from_decisions,
)
from doc_organize.context.decisions import DECISIONS_FILE
from doc_organize.core.models import ConversionResult, Project, TaxonomyAxis, TaxonomyEntry
from tests.unit.fake_llm import fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

TEXT = "Este manual describe el sistema de gestión de la calidad de la organización y sus procesos principales."


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, stem: str, title: str = "Manual de calidad", *, sha: str | None = "sha-1", json_file: bool = True) -> ConversionResult:
    folder = tmp_path / "entrada" / "Calidad"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    if json_file:
        json_path.write_text(json.dumps({"title": title, "chunks": [{"text": TEXT}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(title, encoding="utf-8")
    return ConversionResult(
        source_path=str(folder / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md") if json_file else None,
        json_path=str(json_path) if json_file else None,
        success=json_file,
        source_sha256=sha,
    )


def _manifest():
    domains = [TaxonomyEntry(slug="calidad", name="Calidad", keywords=["calidad"]), TaxonomyEntry(slug="seguridad", name="Seguridad")]
    types = [TaxonomyEntry(slug="manual", name="Manual", keywords=["manual"]), TaxonomyEntry(slug="politica", name="Política")]
    topics = TaxonomyAxis(
        key="topics",
        name="Temas",
        multiple=True,
        rules=False,
        entries=[TaxonomyEntry(slug="auditoria", name="Auditoría"), TaxonomyEntry(slug="iso-9001", name="ISO 9001")],
    )
    return two_axis_manifest(domains, types, extra_axes=[topics])


def _decision(stem: str, action: str = "set_axis", sha: str | None = "sha-1", **axes: list[str]) -> ClassificationDecision:
    return ClassificationDecision(document_key=f"Calidad/{stem}.pdf", action=action, axes=axes, source_sha256=sha, id=f"d-{stem}-{action}")  # type: ignore[arg-type]


async def _build(tmp_path, documents, decisions, **kwargs):
    kwargs.setdefault("taxonomy_manifest", _manifest())
    context = await ContextBuilder().build(
        _project(tmp_path), documents, decisions=decisions, scan_roots=[str(tmp_path / "entrada")], ai_cache=False, **kwargs
    )
    by_path = {document.source_path: (domain.slug, document) for domain in context.domains for document in domain.documents}
    return context, by_path


# --- ClassificationDecision -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "axes"),
    [("set_axis", {}), ("set_axis", {"a": ["x"], "b": ["y"]}), ("confirm", {}), ("exclude", {"a": ["x"]})],
)
def test_decision_validates_its_axes(action, axes) -> None:
    with pytest.raises(ValidationError):
        ClassificationDecision(document_key="a.pdf", action=action, axes=axes)


# --- Almacén -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_replaces_what_a_new_decision_overrides_and_keeps_the_history(tmp_path) -> None:
    store = ClassificationDecisionStore(tmp_path)
    confirm = await store.add(ClassificationDecision(document_key="a.pdf", action="confirm", axes={"domains": ["calidad"]}, author="ana"))
    first = await store.add(ClassificationDecision(document_key="a.pdf", action="set_axis", axes={"topics": ["iso-9001"]}))
    second = await store.add(ClassificationDecision(document_key="a.pdf", action="set_axis", axes={"topics": ["auditoria"]}, author="luis"))
    other = await store.add(ClassificationDecision(document_key="b.pdf", action="exclude"))

    assert [d.id for d in await store.load()] == [confirm.id, second.id, other.id]  # el confirm se conserva
    [replaced] = await store.revoked()
    assert (replaced.id, replaced.revoke_reason, replaced.revoked_by) == (first.id, "replaced", "luis")

    excluded = await store.add(ClassificationDecision(document_key="a.pdf", action="exclude"))
    assert [d.id for d in await store.load()] == [other.id, excluded.id]
    assert await store.revoke(other.id, author="ana", reason="error") is True
    assert await store.revoke("no-existe") is False
    assert [d.id for d in await store.load()] == [excluded.id]
    assert [d.revoke_reason for d in await store.revoked()] == ["replaced", "replaced", "replaced", "error"]
    assert json.loads((tmp_path / DECISIONS_FILE).read_text(encoding="utf-8"))["schema"] == 1


@pytest.mark.asyncio
async def test_store_without_file_has_no_decisions(tmp_path) -> None:
    assert await ClassificationDecisionStore(tmp_path).load() == []


# --- Aplicación en la construcción -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_axis_moves_the_document_and_marks_it_human(tmp_path) -> None:
    document = _document(tmp_path, "manual")

    context, by_path = await _build(tmp_path, [document], [_decision("manual", domains=["seguridad"])])

    slug, result = by_path[document.source_path]
    assert slug == "seguridad"
    assert [(v.slug, v.name, v.confidence, v.classified_by) for v in result.classification.axes["domains"]] == [
        ("seguridad", "Seguridad", 1.0, "human")
    ]
    assert result.classification.axes["material_types"][0].classified_by == "rules"  # lo no decidido sigue de las reglas
    assert (result.classified_by, result.confidence) == ("human", 1.0)
    assert [domain.slug for domain in context.domains] == ["seguridad"]  # sin dominio «calidad» vacío
    assert (context.decisions_applied, context.stale_decisions, context.orphan_decisions) == (1, [], [])


@pytest.mark.asyncio
async def test_confirm_fixes_every_axis_and_a_later_set_axis_wins_in_its_axis(tmp_path) -> None:
    document = _document(tmp_path, "manual")
    confirm = _decision("manual", "confirm", domains=["calidad"], material_types=["politica"], topics=["auditoria"])

    _, by_path = await _build(tmp_path, [document], [confirm, _decision("manual", topics=["iso-9001"])])

    _, result = by_path[document.source_path]
    assert result.material_type == "politica" and result.material_type_name == "Política"
    assert {key: [(v.slug, v.classified_by) for v in values] for key, values in result.classification.axes.items()} == {
        "domains": [("calidad", "human")],
        "material_types": [("politica", "human")],
        "topics": [("iso-9001", "human")],
    }


@pytest.mark.asyncio
async def test_the_ai_never_asks_for_decided_axes(tmp_path) -> None:
    decided = _document(tmp_path, "decidido")
    empty = _document(tmp_path, "vacio")
    asked = _document(tmp_path, "otro")
    llm = fake_client(classify=lambda request: {"topics": "auditoria"})

    _, by_path = await _build(
        tmp_path,
        [decided, empty, asked],
        [_decision("decidido", topics=["iso-9001"]), _decision("vacio", topics=[])],  # vacío decidido = «ninguno»
        llm=llm,
        ai_scope="missing_axes",
    )

    asked_titles = [request.body["messages"][-1]["content"] for request in llm.proxy.calls("classify")]
    assert len(asked_titles) == 1
    assert by_path[decided.source_path][1].classification.slugs("topics") == ["iso-9001"]
    assert by_path[empty.source_path][1].classification.slugs("topics") == []
    assert by_path[asked.source_path][1].classification.axes["topics"][0].classified_by == "ai"


@pytest.mark.asyncio
async def test_exclude_takes_documents_out_of_the_context(tmp_path) -> None:
    kept = _document(tmp_path, "manual")
    excluded = _document(tmp_path, "borrador")
    broken = _document(tmp_path, "roto", json_file=False)

    context, by_path = await _build(tmp_path, [kept, excluded, broken], [_decision("borrador", "exclude"), _decision("roto", "exclude", sha="sha-1")])

    assert list(by_path) == [kept.source_path]
    assert context.unclassified_details == []
    assert context.excluded_documents == [excluded.source_path, broken.source_path]
    assert context.decisions_applied == 2


@pytest.mark.asyncio
async def test_stale_and_orphan_decisions_are_reported_and_not_applied(tmp_path) -> None:
    changed = _document(tmp_path, "cambiado", sha="sha-2")
    document = _document(tmp_path, "manual")
    broken = _document(tmp_path, "roto", json_file=False)
    decisions = [
        _decision("cambiado", domains=["seguridad"]),  # decidida sobre sha-1
        _decision("manual", domains=["inventado"]),
        ClassificationDecision(id="eje", document_key="Calidad/manual.pdf", action="set_axis", axes={"no_existe": ["x"]}),
        ClassificationDecision(id="dos", document_key="Calidad/manual.pdf", action="set_axis", axes={"domains": ["calidad", "seguridad"]}),
        _decision("ausente", domains=["calidad"]),
        _decision("roto", domains=["calidad"]),  # sin `.json` no se puede clasificar
        _decision("manual", sha=None, material_types=["politica"]),  # sin huella: vale para cualquier versión
    ]

    context, by_path = await _build(tmp_path, [changed, document, broken], decisions)

    assert [(i.decision_id, i.reason) for i in context.stale_decisions] == [
        ("d-cambiado-set_axis", "source_changed"),
        ("d-manual-set_axis", "unknown_value"),
        ("eje", "unknown_axis"),
        ("dos", "unknown_value"),
    ]
    assert [(i.document_key, i.reason) for i in context.orphan_decisions] == [
        ("Calidad/ausente.pdf", "missing_document"),
        ("Calidad/roto.pdf", "missing_document"),
    ]
    assert by_path[changed.source_path][0] == "calidad"
    assert by_path[document.source_path][1].material_type == "politica"
    assert context.decisions_applied == 1


@pytest.mark.asyncio
async def test_without_manifest_decisions_are_not_applied(tmp_path) -> None:
    document = _document(tmp_path, "manual")

    context, _ = await _build(tmp_path, [document], [_decision("manual", domains=["seguridad"])], taxonomy_manifest=None)

    assert [(i.reason, i.decision_id) for i in context.stale_decisions] == [("no_manifest", "d-manual-set_axis")]
    assert context.decisions_applied == 0


@pytest.mark.asyncio
async def test_build_reads_the_project_decisions_by_default_and_survives_a_broken_file(tmp_path) -> None:
    document = _document(tmp_path, "manual")
    await ClassificationDecisionStore(tmp_path).add(_decision("manual", domains=["seguridad"]))

    _, by_path = await _build(tmp_path, [document], True)
    assert by_path[document.source_path][0] == "seguridad"
    _, by_path = await _build(tmp_path, [document], False)
    assert by_path[document.source_path][0] == "calidad"

    (tmp_path / DECISIONS_FILE).write_text("{roto", encoding="utf-8")
    context, by_path = await _build(tmp_path, [document], True)
    assert by_path[document.source_path][0] == "calidad" and context.decisions_applied == 0


@pytest.mark.asyncio
async def test_decisions_give_a_reference_for_evaluation(tmp_path) -> None:
    documents = [_document(tmp_path, "manual"), _document(tmp_path, "politica", title="Política de seguridad")]
    decisions = [
        _decision("manual", "confirm", domains=["calidad"], material_types=["manual"]),
        _decision("politica", domains=["seguridad"]),
        _decision("otro", "exclude"),
    ]
    context, _ = await _build(tmp_path, documents, False)

    gold = gold_from_decisions(decisions)
    report = evaluate_classification(context, gold, roots=[str(tmp_path / "entrada")])

    assert [label.document for label in gold.labels] == ["Calidad/manual.pdf", "Calidad/politica.pdf"]
    assert (report.axes["domains"].labelled, report.axes["domains"].accuracy) == (2, 0.5)
    assert report.axes["material_types"].accuracy == 1.0
