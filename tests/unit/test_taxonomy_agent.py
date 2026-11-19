"""`TaxonomyDesignAgent` (M8, G5): herramientas de solo lectura, borrador comprobado por reglas, sin efectos."""

import hashlib
import json

from pathlib import Path
from typing import Any

import pytest

from doc_organize.ai.agents import FINISH_TOOL, AgentLimits
from doc_organize.context.taxonomy_agent import TaxonomyDesignAgent
from doc_organize.context.taxonomy_check import RulesCorpus
from doc_organize.core.models import ProjectProfile, TaxonomyManifest
from doc_organize.core.progress import CancelToken
from tests.unit.fake_llm import FakeRequest, agent_script, call_tools, fake_llm, say
from tests.unit.test_taxonomy_check import base_manifest, make_documents

#: Los cambios que llevan la plantilla de prueba a cubrir todos los dominios sin conflictos.
BETTER = [
    {"axis": "domains", "action": "update", "slug": "calidad", "add_keywords": ["auditoría"]},
    {"axis": "domains", "action": "update", "slug": "seguridad", "keywords": ["información"]},
    {"axis": "domains", "action": "add", "slug": "gobierno", "name": "Gobierno", "description": "Órganos de gobierno", "keywords": ["comité"]},
]


def _base() -> TaxonomyManifest:
    return base_manifest().model_copy(update={"title": "Plantilla", "profile": ProjectProfile(context="SGSI y calidad")})


def _result(request: FakeRequest) -> Any:
    """El resultado de la última herramienta, tal como lo recibió el modelo (`{"error": texto}` si no es JSON: la
    respuesta del runner a un `finish` no válido)."""
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
async def test_edits_the_draft_proposes_it_and_writes_nothing(tmp_path) -> None:
    documents = make_documents(tmp_path)
    base = _base()
    results: list[Any] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools(("overview", {})),
            _recording(results, call_tools(("edit_draft", {"changes": BETTER}))),
            _recording(results, call_tools((FINISH_TOOL, {"rationale": "Separo gobierno y desempato auditorías"}))),
        )
    )
    before = _snapshot(tmp_path)

    proposal = await TaxonomyDesignAgent(llm).propose(documents, base=base, instructions="Separa el gobierno")

    assert _snapshot(tmp_path) == before  # solo lectura: no escribe nada en el proyecto
    assert proposal.run.finished and proposal.manifest is not None and proposal.improves is True and proposal.edits == 1
    assert proposal.rationale == "Separo gobierno y desempato auditorías"
    domains = proposal.manifest.folder_axis
    assert [entry.slug for entry in domains.entries] == ["calidad", "seguridad", "gobierno"]
    assert domains.entries[0].keywords == ["iso 9001", "auditoría"] and domains.entries[1].keywords == ["información"]
    assert proposal.manifest.title == "Plantilla" and proposal.manifest.profile == base.profile  # lo que no toca el agente
    assert base.folder_axis.entries[0].keywords == ["iso 9001"]  # el de partida no cambia
    assert proposal.base_report is not None and proposal.base_report.axis("domains").conflicts == 1  # type: ignore[union-attr]
    assert proposal.report is not None and proposal.report.axis("domains").covered == 5  # type: ignore[union-attr]
    assert "gobierno" in (proposal.markdown() or "")
    overview, edited = results
    assert overview["documents"] == 5 and {"folder": "Calidad", "documents": 1} in overview["folders"]
    assert overview["report"]["axes"]["domains"]["conflicts"] == 1 and overview["draft"]["axes"][0]["key"] == "domains"
    assert edited["improves_on_base"] is True and edited["axes"]["domains"]["covered"] == 5 and edited["edits"] == 1
    first = llm.proxy.calls("agent")[0].body  # type: ignore[attr-defined]
    assert "Cómo puntúan las reglas" in first["messages"][0]["content"] and "Separa el gobierno" in first["messages"][1]["content"]
    assert {tool["function"]["name"] for tool in first["tools"]} == {
        "overview",
        "search_documents",
        "read_document",
        "edit_draft",
        "undo_edit",
        "set_draft",
        FINISH_TOOL,
    }


@pytest.mark.asyncio
async def test_invalid_edits_change_nothing_and_undo_restores(tmp_path) -> None:
    results: list[Any] = []
    bad_edits = [
        [{"axis": "otro", "action": "add", "slug": "x"}],
        [{"axis": "domains", "action": "add", "slug": "calidad"}],
        [{"axis": "domains", "action": "add", "slug": "Con Espacios"}],
        [{"axis": "domains", "action": "update", "slug": "no-existe"}],
        [{"axis": "domains", "action": "rename", "slug": "calidad"}],
        [BETTER[0], {"axis": "domains", "action": "remove", "slug": "no-existe"}],  # el primero tampoco se aplica
    ]
    script = [call_tools(("edit_draft", {"changes": bad_edits[0]}))]
    script += [_recording(results, call_tools(("edit_draft", {"changes": changes}))) for changes in bad_edits[1:]]
    script += [
        _recording(results, call_tools(("edit_draft", {"changes": [BETTER[2]]}))),
        _recording(results, call_tools(("undo_edit", {}))),
        _recording(results, call_tools(("undo_edit", {}))),
        _recording(results, call_tools((FINISH_TOOL, {"rationale": "sin cambios"}))),
    ]
    llm = fake_llm(agent=agent_script(*script))

    proposal = await TaxonomyDesignAgent(llm, limits=AgentLimits(max_steps=20)).propose(make_documents(tmp_path), base=_base())

    errors = [result.get("error", "") for result in results[:6]]
    assert "no existe; los ejes son" in errors[0] and "ya existe" in errors[1] and "no válido" in errors[2]
    assert "sus entradas son" in errors[3] and "acción 'rename'" in errors[4] and "cambio 2" in errors[5]
    added, undone, nothing = results[6:9]
    assert added["axes"]["domains"]["entry_counts"]["gobierno"] == 1 and undone["edits"] == 0
    assert "deshacer" in nothing["error"]
    assert proposal.manifest is not None and proposal.manifest.axes == _base().axes and proposal.improves is False


@pytest.mark.asyncio
async def test_search_and_read_documents(tmp_path) -> None:
    results: list[Any] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools(("search_documents", {"query": "SEGURIDAD"})),
            _recording(results, call_tools(("search_documents", {"folder": "Calidad"}))),
            _recording(results, call_tools(("read_document", {"key": "Seguridad/politica.pdf", "max_chars": 120}))),
            _recording(results, call_tools(("read_document", {"key": "no/existe.pdf"}))),
            _recording(results, call_tools((FINISH_TOOL, {"rationale": "ok"}))),
        )
    )

    await TaxonomyDesignAgent(llm).propose(make_documents(tmp_path), base=_base())

    by_query, by_folder, read, missing = results
    assert by_query["total"] == 3 and {item["key"] for item in by_query["documents"]} == {
        "Auditorias/auditoria.pdf",
        "Seguridad/politica.pdf",
        "Seguridad/plan.pdf",
    }
    assert by_folder == {"total": 1, "offset": 0, "documents": [{"key": "Calidad/manual.pdf", "title": "Manual de calidad"}]}
    assert read["title"] == "Política de seguridad" and read["text"].startswith("Política de seguridad de la información")
    assert "no hay ningún documento" in missing["error"]


@pytest.mark.asyncio
async def test_set_draft_keeps_the_axes_of_the_base(tmp_path) -> None:
    base = _base()
    changed = {"axes": [axis.model_dump(exclude_none=True) for axis in base.axes[:2]]}  # sin el eje de marcos
    results: list[Any] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools(("set_draft", {"manifest": changed})),
            _recording(results, call_tools(("set_draft", {"manifest": {"axes": [{"key": "x"}]}}))),
            _recording(results, call_tools((FINISH_TOOL, {"rationale": "x"}))),
        )
    )

    proposal = await TaxonomyDesignAgent(llm).propose(make_documents(tmp_path), base=base)

    assert "conserva los ejes" in results[0]["error"] and "manifiesto no válido" in results[1]["error"]
    assert proposal.manifest is not None and proposal.manifest.axes == base.axes


@pytest.mark.asyncio
async def test_without_base_the_agent_must_set_a_draft(tmp_path) -> None:
    full = {"axes": [axis.model_dump(exclude_none=True) for axis in _base().axes]}
    results: list[Any] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools(("edit_draft", {"changes": BETTER})),
            _recording(results, call_tools((FINISH_TOOL, {"rationale": "pronto"}))),
            _recording(results, call_tools(("set_draft", {"manifest": full}))),
            call_tools((FINISH_TOOL, {"rationale": "nuevo"})),
        )
    )
    corpus = await RulesCorpus.load(make_documents(tmp_path))

    proposal = await TaxonomyDesignAgent(llm).propose(corpus)

    assert "set_draft" in results[0]["error"]
    assert "No hay manifiesto de partida" in llm.proxy.calls("agent")[0].body["messages"][1]["content"]  # type: ignore[attr-defined]
    assert proposal.manifest is not None and proposal.base_report is None and proposal.improves is None
    assert proposal.manifest.title is None and proposal.rationale == "nuevo"


@pytest.mark.asyncio
async def test_unfinished_keeps_the_draft_but_proposes_nothing(tmp_path) -> None:
    llm = fake_llm(agent=agent_script(call_tools(("edit_draft", {"changes": BETTER})), call_tools(("overview", {}))))

    proposal = await TaxonomyDesignAgent(llm, limits=AgentLimits(max_steps=2)).propose(make_documents(tmp_path), base=_base())

    assert proposal.run.stop_reason == "max_steps" and proposal.manifest is None and proposal.report is None
    assert proposal.draft is not None and len(proposal.draft.folder_axis.entries) == 3 and proposal.edits == 1


@pytest.mark.asyncio
async def test_cancelled(tmp_path) -> None:
    token = CancelToken()
    token.cancel()
    llm = fake_llm(agent=agent_script(say("no debería llamarse")))

    proposal = await TaxonomyDesignAgent(llm).propose(make_documents(tmp_path), base=_base(), cancel_token=token)

    assert proposal.run.stop_reason == "cancelled" and proposal.manifest is None and llm.proxy.requests == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_needs_readable_documents() -> None:
    with pytest.raises(ValueError, match="legible"):
        await TaxonomyDesignAgent(fake_llm()).propose([])
