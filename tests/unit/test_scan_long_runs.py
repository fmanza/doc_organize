"""Escaneos largos (G38 / L-16, 1.1.0): `max_documents`, cancelación entre documentos del OCR y timeout por documento.

La conversión se sustituye por una falsa (sin Docling); los documentos `scan*.pdf` simulan PDF escaneados: la primera
pasada devuelve `ocr_required=True` y la pasada con OCR los resuelve.
"""

import time

from pathlib import Path
from typing import Any

import pytest

from doc_organize import CancelToken, ScanCommand, ScanOptions
from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, ConversionStatus, DocumentMetadata, ScanEvent, ScanEventType
from doc_organize.projects import ProjectLayout

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class FakeConversion:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, dict[str, Any]]] = []
        self.on_ocr: Any = None

    async def convert(self, doc: DocumentMetadata, output_dir: Path, **kwargs: Any) -> ConversionResult:
        use_ocr = bool(kwargs.get("use_ocr", False))
        self.calls.append((Path(doc.full_path).name, use_ocr, kwargs))
        if use_ocr and self.on_ocr is not None:
            self.on_ocr()
        needs_ocr = Path(doc.full_path).name.startswith("scan") and not use_ocr
        return ConversionResult(source_path=doc.full_path, success=True, ocr_required=needs_ocr)

    def names(self, *, ocr: bool) -> list[str]:
        return [name for name, use_ocr, _ in self.calls if use_ocr is ocr]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeConversion:
    conversion = FakeConversion()

    async def _convert(self: DocumentConverter, doc: DocumentMetadata, output_dir: Path, **kwargs: Any) -> ConversionResult:
        return await conversion.convert(doc, output_dir, **kwargs)

    monkeypatch.setattr(DocumentConverter, "convert_document", _convert)
    return conversion


def _source(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path.resolve() / "origen"
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(PDF + name.encode())
    return folder


async def _scan(layout: ProjectLayout, source: Path, options: ScanOptions, **kwargs: Any) -> list[ScanEvent]:
    return [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(source)],
            output_dir=layout.conversion_dir,
            cache_db=layout.cache_db,
            folders_json=layout.folders_json,
            options=options,
            **kwargs,
        )
    ]


async def _statuses(layout: ProjectLayout) -> dict[str, ConversionStatus | None]:
    async with CacheManager(layout.cache_db) as cache:
        return {Path(path).name: entry.conversion_status for path, entry in (await cache.load_cache()).items()}


def test_max_documents_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_documents"):
        ScanOptions(max_documents=0)


@pytest.mark.asyncio
async def test_max_documents_stops_cleanly_and_next_call_continues(tmp_path: Path, fake: FakeConversion) -> None:
    source = _source(tmp_path, "a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf")
    layout = ProjectLayout(tmp_path / "p")
    options = ScanOptions(use_ocr=False, max_documents=2)

    events = await _scan(layout, source, options)

    assert events[-1].event is ScanEventType.COMPLETED
    assert events[-1].data["remaining"] == 3
    assert events[-1].data["stopped_reason"] == "max_documents"
    assert len(fake.calls) == 2
    assert len(await _statuses(layout)) == 2  # lo convertido queda guardado

    second = await _scan(layout, source, options)
    third = await _scan(layout, source, options)

    assert (second[-1].data["remaining"], second[-1].data["stopped_reason"]) == (1, "max_documents")
    assert (third[-1].data["remaining"], third[-1].data["stopped_reason"]) == (0, None)
    assert sorted(fake.names(ocr=False)) == ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"]  # ninguno se repite


@pytest.mark.asyncio
async def test_max_documents_counts_ocr_pass_and_keeps_pending_ocr(tmp_path: Path, fake: FakeConversion) -> None:
    source = _source(tmp_path, "scan1.pdf", "scan2.pdf", "scan3.pdf")
    layout = ProjectLayout(tmp_path / "p")

    events = await _scan(layout, source, ScanOptions(use_ocr=True, max_documents=4))

    summary = events[-1].data
    assert events[-1].event is ScanEventType.COMPLETED
    assert (summary["converted"], summary["ocr_processed"], summary["remaining"]) == (3, 1, 2)
    assert summary["stopped_reason"] == "max_documents"
    statuses = await _statuses(layout)
    assert sorted(statuses.values()) == sorted([ConversionStatus.SUCCESS, ConversionStatus.OCR_PENDING, ConversionStatus.OCR_PENDING])

    fake.calls.clear()
    events = await _scan(layout, source, ScanOptions(use_ocr=True))

    assert fake.names(ocr=False) == []  # no reconvierte lo ya convertido
    assert len(fake.names(ocr=True)) == 2
    assert events[-1].data["stopped_reason"] is None
    assert set((await _statuses(layout)).values()) == {ConversionStatus.SUCCESS}


@pytest.mark.asyncio
async def test_max_documents_exhausted_in_conversion_skips_ocr_phase(tmp_path: Path, fake: FakeConversion) -> None:
    source = _source(tmp_path, "scan1.pdf", "scan2.pdf", "z.pdf")
    layout = ProjectLayout(tmp_path / "p")

    events = await _scan(layout, source, ScanOptions(use_ocr=True, max_documents=2))

    assert not any(event.event is ScanEventType.OCR_STARTED for event in events)
    assert fake.names(ocr=True) == []
    # 1 sin convertir + los candidatos de OCR de lo convertido.
    assert events[-1].data["remaining"] == 1 + events[-1].data["ocr_required"]


@pytest.mark.asyncio
async def test_cancel_during_ocr_stops_between_documents_and_keeps_processed(tmp_path: Path, fake: FakeConversion) -> None:
    source = _source(tmp_path, "scan1.pdf", "scan2.pdf", "scan3.pdf")
    layout = ProjectLayout(tmp_path / "p")
    token = CancelToken()
    fake.on_ocr = token.cancel  # se cancela mientras se procesa el primer OCR

    events = await _scan(layout, source, ScanOptions(use_ocr=True), cancel_token=token)

    assert events[-1].event is ScanEventType.CANCELLED
    assert len(fake.names(ocr=True)) == 1  # el documento en curso termina; el siguiente no empieza
    statuses = await _statuses(layout)
    assert sorted(statuses.values()) == sorted([ConversionStatus.SUCCESS, ConversionStatus.OCR_PENDING, ConversionStatus.OCR_PENDING])

    # La llamada siguiente solo hace el OCR que faltaba.
    fake.calls.clear()
    fake.on_ocr = None
    events = await _scan(layout, source, ScanOptions(use_ocr=True))
    assert events[-1].event is ScanEventType.COMPLETED
    assert (fake.names(ocr=False), len(fake.names(ocr=True))) == ([], 2)


@pytest.mark.asyncio
async def test_document_timeout_is_passed_to_both_passes(tmp_path: Path, fake: FakeConversion) -> None:
    source = _source(tmp_path, "scan1.pdf")

    await _scan(ProjectLayout(tmp_path / "p"), source, ScanOptions(use_ocr=True, document_timeout_s=30))

    assert [kwargs.get("timeout_s") for _, _, kwargs in fake.calls] == [30, 30]


@pytest.mark.asyncio
async def test_default_options_do_not_pass_new_arguments(tmp_path: Path, fake: FakeConversion) -> None:
    """Con los valores por defecto la llamada a `convert_document` es la de 1.0 (quien la sustituye no se rompe)."""
    source = _source(tmp_path, "scan1.pdf")

    events = await _scan(ProjectLayout(tmp_path / "p"), source, ScanOptions(use_ocr=True))

    assert all("timeout_s" not in kwargs for _, _, kwargs in fake.calls)
    assert (events[-1].data["remaining"], events[-1].data["stopped_reason"], events[-1].data["io_errors"]) == (0, None, 0)


@pytest.mark.asyncio
async def test_convert_document_timeout_marks_error_and_discards_converter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from docling.document_converter import DocumentConverter as DoclingConverter

    def _slow_convert(self: Any, source: str) -> Any:
        time.sleep(0.5)
        raise AssertionError("el resultado de un documento que supera el tiempo se descarta")

    monkeypatch.setattr(DoclingConverter, "convert", _slow_convert)
    path = tmp_path / "lento.docx"
    path.write_bytes(b"no importa")
    doc = DocumentMetadata(full_path=str(path), display_name=path.name, extension="docx", size_bytes=10, modified_time=0.0, sha256_hash="0" * 64)

    async with DocumentConverter() as converter:
        first = converter._get_docling(False)
        result = await converter.convert_document(doc, tmp_path / "out", timeout_s=0.05)
        second = converter._get_docling(False)

    assert result.success is False
    assert result.error is not None and "tiempo máximo" in result.error
    assert result.markdown_path is None
    assert second is not first  # el siguiente documento no comparte instancia con el hilo que sigue en marcha
