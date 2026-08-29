"""Tests unitarios de OCRScheduler (REQ-004). Usan Docling real, sin mocks."""

import pytest

from doc_organize.converter import OCRScheduler
from doc_organize.core.models import DocumentMetadata


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
async def test_process_with_ocr_recovers_text_for_candidates(scanned_pdf, tmp_path) -> None:
    scanned_doc = _metadata_for(scanned_pdf)
    output_dir = tmp_path / "Conversión"

    scheduler = OCRScheduler()
    results = await scheduler.process_with_ocr([scanned_doc], output_dir)

    assert len(results) == 1
    result = results[0]
    assert result.success is True
    markdown_text = open(result.markdown_path, encoding="utf-8").read()
    assert "Informe de prueba" in markdown_text
