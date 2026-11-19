"""Cola de revisión (M6, F6): motivos, prioridad y lo que ya decidió una persona."""

from doc_organize import ReviewItem, review_queue
from doc_organize.context.review_queue import REVIEW_PRIORITY
from doc_organize.core.models import (
    AxisValue,
    Context,
    DecisionIssue,
    DocumentClassification,
    Domain,
    DomainDocument,
    TaxonomyAxis,
    TaxonomyEntry,
    UnclassifiedDocument,
)

ROOT = "/mnt/entrada"
NOW = "2026-11-19T00:00:00+00:00"


def _value(slug: str, confidence: float = 0.9, by: str = "rules", verified: bool | None = None) -> AxisValue:
    return AxisValue(
        slug=slug,
        name=slug,
        confidence=confidence,
        classified_by=by,
        evidence="cita" if verified is not None else None,
        evidence_verified=verified,  # type: ignore[arg-type]
    )


def _document(name: str, axes: dict[str, list[AxisValue]], **fields: object) -> DomainDocument:
    return DomainDocument(
        source_path=f"{ROOT}/{name}",
        markdown_path="x.md",
        json_path="x.json",
        title=name,
        document_type="pdf",
        confidence=0.9,
        classification=DocumentClassification(axes=axes),
        **fields,  # type: ignore[arg-type]
    )


def _context(domains: dict[str, list[DomainDocument]], **fields: object) -> Context:
    axes = [
        TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=[TaxonomyEntry(slug="calidad", name="Calidad")]),
        TaxonomyAxis(key="material_types", name="Tipos", organizes="subfolder", entries=[TaxonomyEntry(slug="manual", name="Manual")]),
        TaxonomyAxis(key="topics", name="Temas", multiple=True, threshold=0.7, entries=[TaxonomyEntry(slug="iso", name="ISO")]),
    ]
    return Context(
        project_name="demo",
        created_at=NOW,
        updated_at=NOW,
        taxonomy_axes=axes,
        ai_fallback_threshold=0.5,
        domains=[Domain(slug=slug, name=slug, documents=documents) for slug, documents in domains.items()],
        **fields,  # type: ignore[arg-type]
    )


def _summary(items: list[ReviewItem]) -> list[tuple[str, str, str | None, str | None]]:
    return [(item.reason, item.document_key, item.axis, item.value) for item in items]


def test_every_reason_in_priority_order() -> None:
    context = _context(
        {
            "calidad": [
                _document("ok.pdf", {"domains": [_value("calidad")], "material_types": [_value("manual")], "topics": [_value("iso", 0.8)]}),
                _document("bajo.pdf", {"domains": [_value("calidad", 0.4)], "topics": [_value("iso", 0.6)]}),  # 0.6 < 0.7 del eje
                _document("cita.pdf", {"domains": [_value("calidad", 0.49, "ai", verified=False)]}),
                _document("ia.pdf", {"domains": [_value("calidad")]}, ai_domain="seguridad", ai_confidence=0.7),
            ],
            "sin-clasificar": [_document("vacio.pdf", {"domains": [], "material_types": []}, ai_domain="seguridad")],
        },
        unclassified_details=[UnclassifiedDocument(source_path=f"{ROOT}/roto.pdf", document_type="pdf", reason="incomplete_artifacts")],
        stale_decisions=[DecisionIssue(decision_id="d1", document_key="ok.pdf", reason="source_changed")],
    )

    items = review_queue(context)

    assert _summary(items) == [
        ("stale_decision", "ok.pdf", None, None),
        ("unclassified", "roto.pdf", "domains", None),
        ("unclassified", "vacio.pdf", "domains", None),
        ("rules_ai_disagreement", "ia.pdf", "domains", "calidad"),
        ("unverified_evidence", "cita.pdf", "domains", "calidad"),
        ("low_confidence", "bajo.pdf", "domains", "calidad"),
        ("low_confidence", "bajo.pdf", "topics", "iso"),
    ]
    assert [item.priority for item in items] == sorted(item.priority for item in items)
    assert items[0].source_path == f"{ROOT}/ok.pdf" and items[0].detail == "source_changed"
    assert items[1].detail == "incomplete_artifacts"
    assert items[3].detail == "La IA propuso «seguridad»" and items[3].confidence == 0.7
    assert items[4].detail == "cita"


def test_human_decisions_leave_the_queue() -> None:
    context = _context(
        {
            "calidad": [
                _document(
                    "decidido.pdf", {"domains": [_value("calidad", 1.0, "human")], "topics": [_value("iso", 0.3, "human")]}, ai_domain="seguridad"
                ),
            ]
        }
    )

    assert review_queue(context) == []


def test_keys_use_the_given_roots() -> None:
    context = _context({"calidad": [_document("ENS/bajo.pdf", {"domains": [_value("calidad", 0.2)]})]})

    [item] = review_queue(context, roots=["/mnt"])

    assert item.document_key == "entrada/ENS/bajo.pdf"


def test_priorities_cover_every_reason() -> None:
    assert sorted(REVIEW_PRIORITY.values()) == list(range(len(REVIEW_PRIORITY)))
