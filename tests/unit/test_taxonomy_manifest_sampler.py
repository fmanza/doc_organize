"""Tests de select_document_sample (muestreo de documentos para el borrador de taxonomía por IA)."""

import json

from pathlib import Path

import pytest

from doc_organize.context.taxonomy_manifest_sampler import select_document_sample
from doc_organize.core.models import ConversionResult


def _make_document(
    tmp_path: Path,
    folder: str,
    stem: str,
    *,
    title: str | None = "Título",
    chunks: list[str] | None = None,
    readable_json: bool = True,
) -> ConversionResult:
    source_dir = tmp_path / "root" / folder
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / f"{stem}.pdf"
    source.write_bytes(b"%PDF-1.4")
    json_path = source_dir / f"{stem}.json"
    if readable_json:
        json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text} for text in (chunks or [])]}), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(source_dir / f"{stem}.md"), json_path=str(json_path), success=True)


@pytest.mark.asyncio
async def test_returns_folder_title_and_joined_chunks_text(tmp_path) -> None:
    document = _make_document(tmp_path, "Ciberseguridad", "informe", title="Informe de seguridad", chunks=["ISO 27001", "controles"])

    sample = await select_document_sample([document], sample_size=10)

    assert len(sample) == 1
    assert sample[0].folder == "root/Ciberseguridad"
    assert sample[0].title == "Informe de seguridad"
    assert sample[0].chunks_text == "ISO 27001 controles"


@pytest.mark.asyncio
async def test_caps_at_sample_size(tmp_path) -> None:
    documents = [_make_document(tmp_path, "Calidad", f"doc{i}") for i in range(5)]

    sample = await select_document_sample(documents, sample_size=3)

    assert len(sample) == 3


@pytest.mark.asyncio
async def test_round_robins_across_folders_before_repeating_a_folder(tmp_path) -> None:
    """Con 4 documentos en "Calidad" y 1 en "Ciberseguridad", una muestra de 2 debe incluir el de
    Ciberseguridad -- no los 2 primeros alfabéticos de Calidad -- para dar diversidad real."""
    calidad_docs = [_make_document(tmp_path, "Calidad", f"doc{i}") for i in range(4)]
    ciberseguridad_doc = _make_document(tmp_path, "Ciberseguridad", "unico")

    sample = await select_document_sample([*calidad_docs, ciberseguridad_doc], sample_size=2)

    folders = {item.folder for item in sample}
    assert folders == {"root/Calidad", "root/Ciberseguridad"}


@pytest.mark.asyncio
async def test_is_deterministic_across_calls(tmp_path) -> None:
    documents = [_make_document(tmp_path, "Calidad", f"doc{i}") for i in range(3)] + [
        _make_document(tmp_path, "Ciberseguridad", f"doc{i}") for i in range(3)
    ]

    first = await select_document_sample(documents, sample_size=4)
    second = await select_document_sample(documents, sample_size=4)

    assert [(item.folder, item.title) for item in first] == [(item.folder, item.title) for item in second]


@pytest.mark.asyncio
async def test_skips_documents_with_unreadable_json(tmp_path) -> None:
    readable = _make_document(tmp_path, "Calidad", "bueno")
    broken = _make_document(tmp_path, "Calidad", "roto", readable_json=False)

    sample = await select_document_sample([readable, broken], sample_size=10)

    assert len(sample) == 1
    assert sample[0].title == "Título"


@pytest.mark.asyncio
async def test_empty_documents_returns_empty_sample(tmp_path) -> None:
    assert await select_document_sample([], sample_size=10) == []
