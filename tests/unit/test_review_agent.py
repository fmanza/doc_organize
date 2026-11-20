"""`ReviewAgent` y `audit_taxonomy` (M8, G6): el revisor propone sin aplicar; el auditor da estadísticas y propuestas."""

import hashlib
import json

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from doc_organize.ai.agents import FINISH_TOOL
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.review_agent import ReviewAgent, ReviewProposal, audit_taxonomy
from doc_organize.context.review_queue import ReviewItem, review_queue
from doc_organize.context.taxonomy_check import RulesCorpus
from doc_organize.core.models import Context, Project
from tests.unit.fake_llm import FakeRequest, agent_script, call_tools, fake_llm
from tests.unit.test_taxonomy_check import base_manifest, make_documents


async def _context(tmp_path: Path) -> tuple[Context, list[Any]]:
    documents = make_documents(tmp_path)
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    context = await ContextBuilder().build(project, documents, taxonomy_manifest=base_manifest(), persist=False)
    return context, documents


def _result(request: FakeRequest) -> Any:
    content = request.body["messages"][-1]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": content}


def _recording(results: list[Any], then: dict[str, Any]) -> Any:
    def respond(request: FakeRequest) -> dict[str, Any]:
        results.append(_result(request))
        return then

    return respond


def _snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.mark.asyncio
async def test_proposes_decisions_without_applying_them(tmp_path) -> None:
    context, documents = await _context(tmp_path)
    acta = "Otros/acta.pdf"  # sin dominio por reglas: está en la cola
    results: list[Any] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools(("list_queue", {})),
            _recording(results, call_tools(("get_document", {"key": acta}))),
            _recording(
                results,
                call_tools(
                    (
                        "propose_decision",
                        {
                            "document_key": acta,
                            "action": "set_axis",
                            "axes": {"domains": ["calidad"]},
                            "rationale": "El comité trata la calidad",
                            "evidence": "Acta de la reunión del comité.",
                        },
                    )
                ),
            ),
            _recording(
                results,
                call_tools(("propose_decision", {"document_key": acta, "action": "set_axis", "axes": {"domains": ["gobierno"]}, "rationale": "x"})),
            ),
            _recording(
                results,
                call_tools(
                    (
                        "propose_decision",
                        {"document_key": acta, "action": "set_axis", "axes": {"domains": ["calidad", "seguridad"]}, "rationale": "x"},
                    )
                ),
            ),
            _recording(results, call_tools(("propose_decision", {"document_key": "Calidad/no-esta.pdf", "action": "exclude", "rationale": "x"}))),
            _recording(
                results,
                call_tools(("propose_decision", {"document_key": acta, "action": "exclude", "axes": {"domains": ["calidad"]}, "rationale": "x"})),
            ),
            _recording(results, call_tools((FINISH_TOOL, {"summary": "Una propuesta"}))),
        )
    )
    before = _snapshot(tmp_path)

    review = await ReviewAgent(llm).propose(context, corpus=await RulesCorpus.load(documents))

    assert _snapshot(tmp_path) == before  # ni decisiones ni contexto: nada escrito
    queue, document, recorded, unknown_slug, two_values, not_in_queue, invalid_action = results
    assert any(item["key"] == acta and any(reason["reason"] == "unclassified" for reason in item["reasons"]) for item in queue["documents"])
    assert document["title"] == "Acta de reunión" and document["text"].startswith("Acta de la reunión") and document["axes"]["domains"] == []
    assert recorded["recorded"] is True
    assert "no están en el catálogo" in unknown_slug["error"] and "exactamente un valor" in two_values["error"]
    assert "no está en tu parte de la cola" in not_in_queue["error"] and "no lleva valores" in invalid_action["error"]
    assert review.run.finished and review.summary == "Una propuesta"
    [proposal] = review.proposals
    assert (proposal.document_key, proposal.action, proposal.axes, proposal.evidence) == (
        acta,
        "set_axis",
        {"domains": ["calidad"]},
        "Acta de la reunión del comité.",
    )
    decision = proposal.to_decision(author="ana")
    assert decision.author == "ana" and decision.reason == "Propuesta del revisor: El comité trata la calidad" and decision.axis == "domains"
    system = llm.proxy.calls("agent")[0].body["messages"][0]["content"]  # type: ignore[attr-defined]
    assert "- calidad: Calidad" in system and "Eje frameworks" in system


@pytest.mark.asyncio
async def test_reads_the_json_without_corpus_and_limits_the_queue(tmp_path) -> None:
    context, _ = await _context(tmp_path)
    items = [ReviewItem(document_key=key, reason="low_confidence") for key in ["Calidad/manual.pdf", "Seguridad/plan.pdf", "Otros/acta.pdf"]]
    results: list[Any] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools(("list_queue", {})),
            _recording(results, call_tools(("get_document", {"key": "Calidad/manual.pdf"}))),
            _recording(results, call_tools(("get_document", {"key": "no/existe.pdf"}))),
            _recording(results, call_tools((FINISH_TOOL, {"summary": "nada"}))),
        )
    )

    review = await ReviewAgent(llm).propose(context, items=items, max_items=2)

    queue, manual, missing = results
    assert [item["key"] for item in queue["documents"]] == ["Calidad/manual.pdf", "Seguridad/plan.pdf"] and len(review.items) == 2
    assert manual["text"].startswith("Manual del sistema") and "no hay ningún documento" in missing["error"]
    assert review.proposals == []


@pytest.mark.asyncio
async def test_needs_a_manifest(tmp_path) -> None:
    context, _ = await _context(tmp_path)
    with pytest.raises(ValueError, match="manifiesto"):
        await ReviewAgent(fake_llm()).propose(context.model_copy(update={"taxonomy_axes": []}))


@pytest.mark.asyncio
async def test_proposals_join_the_review_queue(tmp_path) -> None:
    context, _ = await _context(tmp_path)
    proposal = ReviewProposal(document_key="Otros/acta.pdf", action="set_axis", axes={"domains": ["calidad"]}, rationale="comité")

    queue = review_queue(context, proposals=[proposal])

    [item] = [item for item in queue if item.reason == "reviewer_proposal"]
    assert (item.axis, item.value, item.detail, item.priority) == ("domains", "calidad", "set_axis: comité", 6)
    assert item.proposal_id == proposal.id
    assert item.source_path is not None and item.source_path.endswith("acta.pdf")


@pytest.mark.asyncio
async def test_audit(tmp_path) -> None:
    context, _ = await _context(tmp_path)
    documents = [document for domain in context.domains for document in domain.documents]
    for document in documents[:3]:  # la IA corrigió tres veces el dominio de las reglas
        document.rules_domain, document.ai_domain = "calidad", "seguridad"

    audit = audit_taxonomy(context)

    domains = next(axis for axis in audit.axes if axis.axis == "domains")
    assert audit.documents == 5 and domains.with_value == 4 and domains.value_counts == {"calidad": 2, "seguridad": 2}
    assert domains.classified_by == {"rules": 4}
    kinds = {(finding.kind, finding.axis, tuple(finding.values)) for finding in audit.findings}
    assert ("empty_entry", "material_types", ("procedimiento",)) in kinds
    assert ("rules_ai_confusion", "domains", ("calidad", "seguridad")) in kinds
    assert all(finding.kind != "dominant_entry" or finding.axis != "domains" for finding in audit.findings)
    assert "| domains | 5 | 80,0 % |" in audit.to_markdown() and "Propuestas:" in audit.to_markdown()
    assert [finding.count for finding in audit.findings] == sorted((finding.count for finding in audit.findings), reverse=True)


def test_proposals_have_a_stable_id_that_reaches_the_queue() -> None:
    """Petición de la web (W7): id estable de la propuesta, también en la cola."""
    first = ReviewProposal(document_key="Otros/acta.pdf", action="set_axis", axes={"domains": ["calidad"]}, rationale="x")
    other = ReviewProposal(document_key="Otros/acta.pdf", action="exclude", rationale="y")
    stored = ReviewProposal.model_validate(first.model_dump())

    assert first.id and first.id != other.id and stored.id == first.id
