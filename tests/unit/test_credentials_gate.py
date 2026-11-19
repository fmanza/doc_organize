"""Puerta de M3 (F1, S-F1-3): el valor de una credencial del texto de un documento no sale hacia la IA ni aparece en
`context.json`, los `index.json`, el historial, los logs ni las exportaciones; solo su recuento."""

import io
import json
import logging

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from doc_organize import ContextBuilder, write_context_documents_xlsx
from doc_organize.core.models import ConversionResult, Project, TaxonomyEntry
from tests.unit.fake_llm import FakeLlmClient, FakeRequest, fake_client
from tests.unit.taxonomy_helpers import two_axis_manifest

openpyxl = pytest.importorskip("openpyxl")

SECRET = "Xq7#Secreto-9931"
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def _echoing_ai(*, fail_on: str) -> FakeLlmClient:
    """Un modelo que repite lo que recibe (en la justificación y la descripción) y falla con el documento `fail_on`,
    devolviendo el texto en el error."""

    def classify(request: FakeRequest) -> object:
        user = request.body["messages"][-1]["content"]
        if fail_on in request.title:
            return httpx.Response(500, text=f"El proxy rechazó: {user[:80]}")
        folder, subfolder = request.axes[:2]
        return {"reasoning": user[:300], folder: {"value": "calidad", "confidence": 0.8}, subfolder: {"value": None, "confidence": 0.0}}

    def enrich(request: FakeRequest) -> object:
        return {"description": request.body["messages"][-1]["content"][:200], "keywords": ["acceso"]}

    return fake_client(classify=classify, enrich=enrich)


def _documents(root: Path) -> list[ConversionResult]:
    (root / "varios").mkdir(parents=True)
    texts = {
        "acta": f"Acta de la reunión. Acceso al servidor: password: {SECRET} y token {TOKEN}.",
        "fallo": f"Anexo técnico con la clave = {SECRET}",
    }
    documents = []
    for stem, text in texts.items():
        json_path = root / f"{stem}.json"
        json_path.write_text(json.dumps({"title": stem.title(), "chunks": [{"text": text}]}), encoding="utf-8")
        (root / f"{stem}.md").write_text(text, encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(root / "varios" / f"{stem}.pdf"), markdown_path=str(root / f"{stem}.md"), json_path=str(json_path), success=True
            )
        )
    return documents


@pytest.mark.asyncio
async def test_credential_values_never_leave_nor_get_stored(tmp_path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    manifest = two_axis_manifest([TaxonomyEntry(slug="calidad", name="Calidad")], [TaxonomyEntry(slug="politica", name="Política")])
    ai = _echoing_ai(fail_on="Fallo")

    context = await ContextBuilder().build(
        project,
        _documents(tmp_path),
        taxonomy_manifest=manifest,
        llm=ai,
        ai_scope="unclassified",
        enrich=True,
    )

    assert ai.sent_texts and all(SECRET not in text and TOKEN not in text for text in ai.sent_texts)
    assert {finding.source_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for finding in context.credential_findings} == {"acta.pdf", "fallo.pdf"}
    assert all(set(finding.rules.values()) <= {1, 2} for finding in context.credential_findings)

    conversion = {tmp_path / f"{stem}{suffix}" for stem in ("acta", "fallo") for suffix in (".json", ".md")}  # el propio documento
    stored = [path for path in tmp_path.rglob("*") if path.is_file() and path.suffix in (".json", ".jsonl", ".md") and path not in conversion]
    assert "context.json" in {path.name for path in stored}
    assert any(path.name == "CONTEXT_HISTORY.jsonl" for path in stored)
    for path in stored:
        text = path.read_text(encoding="utf-8")
        assert SECRET not in text and TOKEN not in text, path.name

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "Falló la clasificación por IA" in logged  # el fallo se registró…
    assert SECRET not in logged and TOKEN not in logged  # …sin el valor

    buffer = io.BytesIO()
    write_context_documents_xlsx(buffer, context)
    cells = [str(cell) for sheet in openpyxl.load_workbook(buffer).worksheets for row in sheet.iter_rows(values_only=True) for cell in row]
    assert not any(SECRET in cell or TOKEN in cell for cell in cells)
