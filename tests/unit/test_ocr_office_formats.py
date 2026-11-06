"""Regresion G39 / L-17 (1.0.1): los formatos de `SimplePipeline` (docx, xlsx...) no requieren OCR.

Docling solo calcula `confidence.parse_score` en `StandardPdfPipeline` (PDF/imagen); en el resto
queda en `NaN` por defecto, y antes de 1.0.1 eso los marcaba `ocr_required` y los convertia dos veces.
Docling real sobre documentos sinteticos, sin mocks (de ahi `slow`).
"""

from pathlib import Path

import pytest

from doc_organize import ScanCommand, ScanOptions
from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import ConversionStatus, DocumentMetadata, ScanEventType


def _make_docx(path: Path) -> None:
    import docx

    document = docx.Document()
    document.add_heading("Informe sintetico", level=1)
    document.add_paragraph("Texto nativo de un documento Word de prueba.")
    document.save(str(path))


def _make_xlsx(path: Path) -> None:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Concepto", "Importe"])
    sheet.append(["Prueba", 42])
    workbook.save(path)


def _metadata_for(path: Path) -> DocumentMetadata:
    stat = path.stat()
    return DocumentMetadata(
        full_path=str(path),
        display_name=path.name,
        extension=path.suffix.lstrip("."),
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
        sha256_hash="test-hash-not-relevant-here",
    )


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "factory"), [("informe.docx", _make_docx), ("datos.xlsx", _make_xlsx)])
async def test_office_document_never_requires_ocr(tmp_path: Path, name: str, factory) -> None:
    source = tmp_path / name
    factory(source)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(_metadata_for(source), tmp_path / "Conversión", use_ocr=False)

    assert result.success is True
    assert result.ocr_required is False


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_with_ocr_only_sends_scanned_pdf_to_ocr_phase(tmp_path: Path, scanned_pdf: Path) -> None:
    source = tmp_path / "origen"
    source.mkdir()
    _make_docx(source / "informe.docx")
    _make_xlsx(source / "datos.xlsx")
    pdf = source / "scanned.pdf"
    scanned_pdf.replace(pdf)
    project = tmp_path / "proyecto"
    project.mkdir()

    events = [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(source)],
            output_dir=project / "Conversión",
            cache_db=project / "cache.db",
            folders_json=project / "folders.json",
            options=ScanOptions(use_ocr=True, use_gpu=False),
        )
    ]

    ocr_started = [event.data["path"] for event in events if event.event is ScanEventType.OCR_FILE_STARTED]
    assert ocr_started == [str(pdf.resolve())]
    summary = events[-1].data
    assert events[-1].event is ScanEventType.COMPLETED
    assert summary["ocr_required"] == 1
    assert summary["ocr_processed"] == 1

    async with CacheManager(project / "cache.db") as cache:
        entries = await cache.load_cache()
    assert {entry.conversion_status for entry in entries.values()} == {ConversionStatus.SUCCESS}


@pytest.mark.slow
@pytest.mark.asyncio
async def test_legacy_ocr_pending_docx_is_reprocessed_once_and_fixed(tmp_path: Path) -> None:
    """Caché de 1.0.0: un .docx que quedó `OCR_PENDING` pasa a `SUCCESS` en el siguiente escaneo con OCR."""
    source = tmp_path / "origen"
    source.mkdir()
    _make_docx(source / "informe.docx")
    project = tmp_path / "proyecto"
    project.mkdir()
    kwargs = {
        "paths": [str(source)],
        "output_dir": project / "Conversión",
        "cache_db": project / "cache.db",
        "folders_json": project / "folders.json",
    }
    await ScanCommand().run(options=ScanOptions(use_ocr=False, use_gpu=False), **kwargs)
    async with CacheManager(project / "cache.db") as cache:
        (entry,) = (await cache.load_cache()).values()
        await cache.save_entries([entry.model_copy(update={"conversion_status": ConversionStatus.OCR_PENDING})])

    first = await ScanCommand().run(options=ScanOptions(use_ocr=True, use_gpu=False), **kwargs)
    second = await ScanCommand().run(options=ScanOptions(use_ocr=True, use_gpu=False), **kwargs)

    assert (first.ocr_processed, second.ocr_processed) == (1, 0)
    async with CacheManager(project / "cache.db") as cache:
        (entry,) = (await cache.load_cache()).values()
    assert entry.conversion_status == ConversionStatus.SUCCESS
