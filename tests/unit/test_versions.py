"""Versiones de un mismo documento (M7, F5): detección conservadora, `build(versions=)`, decisión de la vigente,
historial y cola de revisión."""

import json

from datetime import UTC, datetime

import pytest

from doc_organize import ClassificationDecision, ContextBuilder, detect_document_versions, review_queue
from doc_organize.context.context_history import diff_contexts
from doc_organize.context.versions import parse_version
from doc_organize.core.models import ConversionResult, Project, TaxonomyEntry
from tests.unit.taxonomy_helpers import two_axis_manifest

# --- Detección ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Manual_Calidad_v1.2.docx", ("manual calidad", (1, 2))),
        ("Manual Calidad v2.pdf", ("manual calidad", (2,))),
        ("Plan_V3.0.pptx", ("plan", (3, 0))),
        ("Politica ver 3.docx", ("politica", (3,))),
        ("Politica ver. 3.docx", ("politica", (3,))),
        ("Procedimiento_rev2.docx", ("procedimiento", (2,))),
        ("Procedimiento Rev. 4.docx", ("procedimiento", (4,))),
        ("Manual versión 1.4.docx", ("manual", (1, 4))),
        ("Norma ed. 2.pdf", ("norma", (2,))),
        ("Guía_edición 3.pdf", ("guia", (3,))),
        ("Manual_v 6.0.pptx", ("manual", (6, 0))),
        ("Seguridad en la Nube_v2-Equipo de Ana.docx", ("seguridad en la nube equipo de ana", (2,))),
    ],
)
def test_explicit_markers_are_versions(name, expected) -> None:
    parsed = parse_version(name)
    assert parsed is not None and parsed[:2] == expected


@pytest.mark.parametrize(
    "name",
    [
        "ISO_9001_v2015.pdf",  # un año no es una versión
        "Acta_2023.docx",
        "Acta 2024 v.docx",
        "Plan_ED_2.docx",  # «ED_2» no es «ed. 2»
        "ENSv2.docx",  # pegado a otra palabra
        "Informe 33000.pptx",
        "Revision de accesos.docx",  # «revision» sin número
        "v2.docx",  # nada más que el marcador
        "Plan_v1_borrador_v2.docx",  # dos marcadores: ambiguo
    ],
)
def test_names_without_an_explicit_marker_are_not_versions(name) -> None:
    assert parse_version(name) is None


def test_groups_need_same_folder_extension_and_rest_of_the_name() -> None:
    paths = [
        "/e/A/Manual_v1.2.docx",
        "/e/A/Manual_v1.10.docx",
        "/e/A/manual_V1.9.docx",  # mayúsculas y separadores no cuentan
        "/e/A/Manual_v2.pdf",  # otra extensión
        "/e/B/Manual_v3.docx",  # otra carpeta
        "/e/A/Anexo_v1_Contrato_A.docx",  # el resto del nombre no coincide (R-F5-1)
        "/e/A/Anexo_v1_Contrato_B.docx",
        "/e/A/Plan_v2.docx",
        "/e/A/Plan_v2.0.docx",  # la misma versión: nada que elegir
    ]

    groups = detect_document_versions(paths)

    assert [(group.current, [m.version for m in group.members]) for group in groups] == [("/e/A/Manual_v1.10.docx", ["1.2", "1.9", "1.10"])]
    [across] = [group for group in detect_document_versions(paths, across_extensions=True) if "manual" in group.key]
    assert across.current == "/e/A/Manual_v2.pdf"


# --- En la construcción ------------------------------------------------------------------------------------------------

TEXT = "Este manual describe el sistema de gestión de la calidad y sus procesos principales en detalle."


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, name: str, sha: str = "sha") -> ConversionResult:
    folder = tmp_path / "entrada" / "Calidad"
    folder.mkdir(parents=True, exist_ok=True)
    stem = name.rsplit(".", 1)[0]
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": "Manual de calidad", "chunks": [{"text": TEXT}]}), encoding="utf-8")
    (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
    return ConversionResult(
        source_path=str(folder / name), markdown_path=str(tmp_path / f"{stem}.md"), json_path=str(json_path), success=True, source_sha256=sha
    )


def _manifest():
    return two_axis_manifest(
        [TaxonomyEntry(slug="calidad", name="Calidad", keywords=["calidad"])], [TaxonomyEntry(slug="manual", name="Manual", keywords=["manual"])]
    )


async def _build(tmp_path, documents, **kwargs):
    kwargs.setdefault("taxonomy_manifest", _manifest())
    return await ContextBuilder().build(_project(tmp_path), documents, scan_roots=[str(tmp_path / "entrada")], ai_cache=False, **kwargs)


def _documents(context):
    return {document.source_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]: document for domain in context.domains for document in domain.documents}


@pytest.mark.asyncio
async def test_all_is_like_1x_and_mark_annotates_every_version(tmp_path) -> None:
    documents = [_document(tmp_path, "Manual_v1.docx"), _document(tmp_path, "Manual_v2.docx"), _document(tmp_path, "Otro.docx")]

    plain = await _build(tmp_path, documents)
    assert plain.versions_mode == "all" and plain.version_groups == [] and _documents(plain)["Manual_v1.docx"].version is None

    marked = await _build(tmp_path, documents, versions="mark")
    docs = _documents(marked)
    assert [(n, docs[n].version, docs[n].is_current) for n in ("Manual_v1.docx", "Manual_v2.docx", "Otro.docx")] == [
        ("Manual_v1.docx", "1", False),
        ("Manual_v2.docx", "2", True),
        ("Otro.docx", None, None),
    ]
    [group] = marked.version_groups
    assert docs["Manual_v1.docx"].version_group == group.key and group.versions == ["1", "2"] and not group.confirmed
    assert group.key == "calidad/manual.docx"  # relativa a la raíz de escaneo, sin la ruta absoluta (petición de la web)
    assert marked.superseded_documents == []


@pytest.mark.asyncio
async def test_current_only_leaves_old_versions_out_and_the_history_says_why(tmp_path) -> None:
    documents = [_document(tmp_path, "Manual_v1.docx"), _document(tmp_path, "Manual_v2.docx")]
    before = await _build(tmp_path, documents)

    context = await _build(tmp_path, documents, versions="current_only")

    assert list(_documents(context)) == ["Manual_v2.docx"]
    assert [path.rsplit("Calidad", 1)[-1][1:] for path in context.superseded_documents] == ["Manual_v1.docx"]
    [change] = diff_contexts(before, context)
    assert change.change == "superseded"


@pytest.mark.asyncio
async def test_a_person_chooses_the_current_version(tmp_path) -> None:
    documents = [_document(tmp_path, "Manual_v1.docx", sha="s1"), _document(tmp_path, "Manual_v2.docx"), _document(tmp_path, "Otro.docx")]
    decisions = [
        ClassificationDecision(id="vigente", document_key="Calidad/Manual_v1.docx", action="set_current_version", source_sha256="s1"),
        ClassificationDecision(id="suelto", document_key="Calidad/Otro.docx", action="set_current_version"),
        ClassificationDecision(id="ausente", document_key="Calidad/Nada_v1.docx", action="set_current_version"),
    ]

    context = await _build(tmp_path, documents, versions="current_only", decisions=decisions, taxonomy_manifest=None)

    assert sorted(_documents(context)) == ["Manual_v1.docx", "Otro.docx"]  # el v2 sale: la vigente es la v1
    assert context.version_groups[0].confirmed is True
    assert context.decisions_applied == 1  # sin manifiesto también: la vigencia no depende del catálogo
    assert [(i.decision_id, i.reason) for i in context.stale_decisions] == [("suelto", "not_versioned")]
    assert [(i.decision_id, i.reason) for i in context.orphan_decisions] == [("ausente", "missing_document")]


@pytest.mark.asyncio
async def test_unconfirmed_groups_go_to_the_review_queue(tmp_path) -> None:
    documents = [_document(tmp_path, "Manual_v1.docx"), _document(tmp_path, "Manual_v2.docx")]

    context = await _build(tmp_path, documents, versions="mark")
    items = [item for item in review_queue(context, roots=[str(tmp_path / "entrada")]) if item.reason == "unconfirmed_version"]

    assert [(item.document_key, item.detail) for item in items] == [("Calidad/Manual_v2.docx", "Versiones 1, 2; vigente propuesta: la más alta")]

    decision = ClassificationDecision(document_key="Calidad/Manual_v2.docx", action="set_current_version")
    confirmed = await _build(tmp_path, documents, versions="mark", decisions=[decision])
    assert not [item for item in review_queue(confirmed, roots=[str(tmp_path / "entrada")]) if item.reason == "unconfirmed_version"]


def test_set_current_version_carries_no_values() -> None:
    with pytest.raises(ValueError, match="no lleva valores"):
        ClassificationDecision(document_key="a_v1.pdf", action="set_current_version", axes={"domains": ["x"]})
