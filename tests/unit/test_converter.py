"""Tests unitarios de DocumentConverter (REQ-003, REQ-004).

Usan Docling real (sin mocks) sobre documentos de fixture generados con
matplotlib/PIL — coherente con la politica del proyecto de no mockear
servicios/componentes reales en tests. Son mas lentos que el resto de la
suite (carga de modelos de Docling), de ahi el marcador `slow`.
"""

import asyncio
import json

import pytest

from doc_organize.converter import DocumentConverter
from doc_organize.core.models import DocumentMetadata


def _read_text(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _metadata_for(path) -> DocumentMetadata:
    stat = path.stat()
    return DocumentMetadata(
        full_path=str(path),
        display_name=path.name,
        extension="pdf",
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
        sha256_hash="test-hash-not-relevant-here",
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_convert_native_pdf_extracts_text_without_ocr(native_pdf, tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(native_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir)

    assert result.success is True
    assert result.ocr_required is False
    assert result.error is None

    markdown_text = await asyncio.to_thread(_read_text, result.markdown_path)
    assert "Informe de prueba" in markdown_text

    document_json = json.loads(await asyncio.to_thread(_read_text, result.json_path))
    assert document_json["sha256_hash"] == doc.sha256_hash
    assert document_json["ocr_required"] is False
    assert any("Informe de prueba" in chunk["text"] for chunk in document_json["chunks"])


@pytest.mark.slow
@pytest.mark.asyncio
async def test_convert_scanned_pdf_without_ocr_flags_ocr_required(scanned_pdf, tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(scanned_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, use_ocr=False)

    assert result.success is True
    assert result.ocr_required is True


@pytest.mark.slow
@pytest.mark.asyncio
async def test_convert_scanned_pdf_with_ocr_recovers_text(scanned_pdf, tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(scanned_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, use_ocr=True)

    assert result.success is True
    markdown_text = await asyncio.to_thread(_read_text, result.markdown_path)
    assert "Informe de prueba" in markdown_text


@pytest.mark.asyncio
async def test_convert_document_reports_error_without_raising(tmp_path) -> None:
    missing = tmp_path / "does-not-exist.pdf"
    doc = DocumentMetadata(
        full_path=str(missing),
        display_name=missing.name,
        extension="pdf",
        size_bytes=0,
        modified_time=0.0,
        sha256_hash="irrelevant",
    )

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, tmp_path / "Conversión")

    assert result.success is False
    assert result.error is not None
    assert result.markdown_path is None
    assert result.json_path is None


@pytest.mark.asyncio
async def test_using_outside_context_manager_raises(tmp_path) -> None:
    from doc_organize.core.exceptions import ConversionError

    converter = DocumentConverter()
    doc = DocumentMetadata(
        full_path=str(tmp_path / "x.pdf"),
        display_name="x.pdf",
        extension="pdf",
        size_bytes=0,
        modified_time=0.0,
        sha256_hash="irrelevant",
    )
    with pytest.raises(ConversionError):
        await converter.convert_document(doc, tmp_path)
