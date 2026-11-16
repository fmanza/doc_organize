"""Lectura concurrente de las propiedades de los originales sin llamar a PDFium a la vez (G44, 1.6.0)."""

import asyncio
import logging
import sys
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pypdfium2
import pytest

from doc_organize.context import context_builder as context_builder_module, document_properties as document_properties_module
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.document_properties import DocumentProperties, read_document_properties
from doc_organize.core.exceptions import ContextNotFoundError, OperationCancelledError
from doc_organize.core.progress import CancelToken
from tests.unit.test_context_builder_enrichment import _by_name, _document, _docx, _project
from tests.unit.test_document_properties import make_pdf

_REAL_PDF_DOCUMENT = pypdfium2.PdfDocument


class _CountingPdfDocument:
    """Doble de `pypdfium2.PdfDocument` que cuenta cuántos documentos hay abiertos a la vez y con qué se abrieron."""

    guard = threading.Lock()
    active = 0
    peak = 0
    sources: list[Any] = []

    def __init__(self, source: Any) -> None:
        cls = type(self)
        with cls.guard:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
            cls.sources.append(source)
        time.sleep(0.002)  # ensancha la ventana en la que dos hilos coincidirían sin cerrojo
        try:
            self._pdf = _REAL_PDF_DOCUMENT(source)
        except BaseException:
            self._leave()
            raise

    def get_metadata_dict(self, **kwargs: Any) -> dict[str, str]:
        return self._pdf.get_metadata_dict(**kwargs)

    def close(self) -> None:
        self._pdf.close()
        self._leave()

    @classmethod
    def _leave(cls) -> None:
        with cls.guard:
            cls.active -= 1

    @classmethod
    def reset(cls) -> None:
        cls.active, cls.peak, cls.sources = 0, 0, []


@pytest.fixture
def counting_pdfium(monkeypatch: pytest.MonkeyPatch) -> type[_CountingPdfDocument]:
    _CountingPdfDocument.reset()
    monkeypatch.setattr(pypdfium2, "PdfDocument", _CountingPdfDocument)
    return _CountingPdfDocument


def _pdfs(tmp_path: Path, count: int) -> list[Path]:
    paths = []
    for i in range(count):
        path = tmp_path / f"doc{i:02d}.pdf"
        path.write_bytes(make_pdf(f"<</Author(Autor {i})/Keywords(k{i})>>"))
        paths.append(path)
    return paths


def test_pdfium_is_never_called_from_two_threads_at_once(tmp_path: Path, counting_pdfium: type[_CountingPdfDocument]) -> None:
    paths = _pdfs(tmp_path, 32)
    damaged = tmp_path / "danado.pdf"
    damaged.write_bytes(b"%PDF-1.4\nbasura")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read_document_properties, [*paths, damaged]))

    assert counting_pdfium.peak == 1
    assert counting_pdfium.active == 0
    assert results[:-1] == [DocumentProperties(author=f"Autor {i}", keywords=[f"k{i}"]) for i in range(32)]
    assert results[-1] == DocumentProperties()


def test_small_pdfs_are_parsed_from_memory_and_large_ones_by_path(
    tmp_path: Path, counting_pdfium: type[_CountingPdfDocument], monkeypatch: pytest.MonkeyPatch
) -> None:
    small, large = _pdfs(tmp_path, 2)
    monkeypatch.setattr(document_properties_module, "_MAX_PDF_BYTES_IN_MEMORY", large.stat().st_size - 1)
    small.write_bytes(make_pdf("<</Author(A)>>"))  # más corto que el límite

    assert read_document_properties(small).author == "A"
    assert read_document_properties(large).author == "Autor 1"

    assert isinstance(counting_pdfium.sources[0], bytes)
    assert counting_pdfium.sources[1] == large


def test_the_pdfium_lock_is_docling_s() -> None:
    """Si Docling mueve o renombra su cerrojo, este test falla en vez de perder la protección en silencio."""
    from docling.utils.locks import pypdfium2_lock

    assert document_properties_module._pdfium_lock() is pypdfium2_lock


def test_a_pdf_conversion_in_another_thread_blocks_the_read(tmp_path: Path) -> None:
    from docling.utils.locks import pypdfium2_lock

    (path,) = _pdfs(tmp_path, 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pypdfium2_lock:  # Docling convirtiendo un PDF en otro hilo
            future = pool.submit(read_document_properties, path)
            time.sleep(0.2)
            assert not future.done()
        assert future.result(timeout=5).author == "Autor 0"


def test_without_docling_s_lock_every_thread_gets_the_same_own_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from docling.utils.locks import pypdfium2_lock

    monkeypatch.setitem(sys.modules, "docling.utils.locks", None)  # la importación lanza ImportError
    document_properties_module._pdfium_lock.cache_clear()
    start = threading.Barrier(8)

    def first_call(_: int) -> object:
        start.wait()  # las 8 primeras llamadas a la vez, como las tareas de ContextBuilder
        return document_properties_module._pdfium_lock()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            locks = set(map(id, pool.map(first_call, range(8))))
        (path,) = _pdfs(tmp_path, 1)
        assert read_document_properties(path).author == "Autor 0"
    finally:
        document_properties_module._pdfium_lock.cache_clear()

    assert locks == {id(document_properties_module._FALLBACK_PDFIUM_LOCK)}
    assert document_properties_module._FALLBACK_PDFIUM_LOCK is not pypdfium2_lock


@pytest.mark.asyncio
async def test_two_different_errors_at_once_raise_the_first_and_log_the_other(caplog: pytest.LogCaptureFixture) -> None:
    both_started = asyncio.Event()
    started = 0

    async def fail(item: int) -> None:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await both_started.wait()
        raise (ValueError if item == 0 else RuntimeError)(f"fallo {item}")

    with caplog.at_level(logging.WARNING), pytest.raises((ValueError, RuntimeError)) as raised:
        await ContextBuilder(properties_concurrency=2)._for_each_bounded([0, 1], fail, None)

    assert not isinstance(raised.value, BaseExceptionGroup)
    assert "Otro error a la vez" in caplog.text


def _builder(concurrency: int) -> ContextBuilder:
    return ContextBuilder(ContextRegistry(), properties_concurrency=concurrency)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4])
async def test_concurrency_does_not_change_the_values(tmp_path: Path, concurrency: int) -> None:
    documents = [_document(tmp_path, f"informe{i}.pdf", make_pdf(f"<</Author(Autor {i})/Subject(Tema {i})>>")) for i in range(6)]
    documents.append(_document(tmp_path, "plan.docx", _docx(tmp_path, "plan.docx", creator="Luis Gil", keywords="auditoría")))
    documents.append(_document(tmp_path, "borrado.pdf"))  # el original ya no existe

    context = await _builder(concurrency).build(_project(tmp_path), documents)

    docs = _by_name(context)
    assert [(docs[f"informe{i}.pdf"].author, docs[f"informe{i}.pdf"].description) for i in range(6)] == [
        (f"Autor {i}", f"Tema {i}") for i in range(6)
    ]
    assert (docs["plan.docx"].author, docs["plan.docx"].keywords) == ("Luis Gil", ["auditoría"])
    assert (docs["borrado.pdf"].author, docs["borrado.pdf"].keywords) == (None, [])
    assert [document.source_path for domain in context.domains for document in domain.documents] == [
        document.source_path for document in documents
    ]  # mismo orden que la entrada, como en 1.5.0


class _SlowReads:
    """Doble de `read_document_properties` que tarda y cuenta cuántas lecturas hay a la vez."""

    def __init__(self, on_call: Any = None) -> None:
        self.guard = threading.Lock()
        self.active = 0
        self.peak = 0
        self.calls = 0
        self.on_call = on_call

    def __call__(self, path: str | Path) -> DocumentProperties:
        with self.guard:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            calls = self.calls
        if self.on_call is not None:
            self.on_call(calls)
        time.sleep(0.03)
        with self.guard:
            self.active -= 1
        return DocumentProperties(author=Path(path).stem)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 3])
async def test_reads_at_most_properties_concurrency_originals_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, concurrency: int) -> None:
    reads = _SlowReads()
    monkeypatch.setattr(context_builder_module, "read_document_properties", reads)
    documents = [_document(tmp_path, f"doc{i}.pdf", b"") for i in range(10)]

    context = await _builder(concurrency).build(_project(tmp_path), documents)

    assert reads.peak == concurrency
    assert reads.calls == 10
    assert sorted(document.author or "" for document in context.domains[0].documents) == [f"doc{i}" for i in range(10)]


@pytest.mark.asyncio
async def test_cancelling_stops_the_reads_and_raises_the_usual_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = CancelToken()
    reads = _SlowReads(on_call=lambda calls: token.cancel() if calls == 3 else None)
    monkeypatch.setattr(context_builder_module, "read_document_properties", reads)
    project = _project(tmp_path)
    documents = [_document(tmp_path, f"doc{i}.pdf", b"") for i in range(20)]

    with pytest.raises(OperationCancelledError):
        await _builder(2).build(project, documents, cancel_token=token)

    assert reads.calls < 20
    with pytest.raises(ContextNotFoundError):  # nunca se persiste un contexto a medias
        await ContextRegistry().load_context(project)


@pytest.mark.parametrize("concurrency", [0, -1])
def test_properties_concurrency_must_be_positive(concurrency: int) -> None:
    with pytest.raises(ValueError, match="properties_concurrency"):
        ContextBuilder(properties_concurrency=concurrency)


def test_default_reads_four_originals_at_once() -> None:
    assert ContextBuilder().properties_concurrency == 4
