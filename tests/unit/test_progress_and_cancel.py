"""Progreso con unidades y cancelación cooperativa (L-2, hueco G2 de doc_organize_web).

La conversión se sustituye por una falsa (sin Docling) para que el escaneo sea rápido y controlable.
"""

from pathlib import Path

import pytest

from doc_organize import CancelToken, OperationCancelledError, ProgressEvent, ScanCommand, ScanOptions
from doc_organize.cache import CacheManager
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, DedupEventType, Project, ScanEventType
from doc_organize.projects import ProjectLayout
from doc_organize.scan.scan_history_store import list_scan_runs

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_cancel_token_is_one_way() -> None:
    token = CancelToken()
    token.raise_if_cancelled()  # sin cancelar: no hace nada

    token.cancel()

    assert token.cancelled
    with pytest.raises(OperationCancelledError):
        token.raise_if_cancelled()


@pytest.fixture
def fake_conversion(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Conversión instantánea que anota el orden de los documentos convertidos."""
    converted: list[str] = []

    async def _convert(self, doc, output_dir, **_: object) -> ConversionResult:
        converted.append(Path(doc.full_path).name)
        return ConversionResult(source_path=doc.full_path, success=True)

    monkeypatch.setattr(DocumentConverter, "convert_document", _convert)
    return converted


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "origen"
    folder.mkdir()
    for name in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        (folder / name).write_bytes(PDF + name.encode())
    return folder


def _scan(layout: ProjectLayout, source: Path, **kwargs: object):
    return ScanCommand().run_streaming(
        paths=[str(source)],
        output_dir=layout.conversion_dir,
        cache_db=layout.cache_db,
        folders_json=layout.folders_json,
        history_log_path=layout.scan_history_log,
        options=ScanOptions(use_ocr=False),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_scan_reports_progress_with_units(tmp_path: Path, source: Path, fake_conversion: list[str]) -> None:
    progress: list[ProgressEvent] = []

    events = [event async for event in _scan(ProjectLayout(tmp_path / "p"), source, on_progress=progress.append)]

    assert events[-1].event is ScanEventType.COMPLETED
    conversion = [p for p in progress if p.phase == "conversion"]
    assert conversion[0].total == 4
    assert [p.processed for p in conversion if p.current is None][-1] == 4
    assert {p.current for p in conversion if p.current} == {str(source / n) for n in ("a.pdf", "b.pdf", "c.pdf", "d.pdf")}
    assert progress[-1].phase == "done"


@pytest.mark.asyncio
async def test_failing_progress_callback_does_not_stop_scan(tmp_path: Path, source: Path, fake_conversion: list[str]) -> None:
    def _boom(_: ProgressEvent) -> None:
        raise RuntimeError("callback roto")

    events = [event async for event in _scan(ProjectLayout(tmp_path / "p"), source, on_progress=_boom)]

    assert events[-1].event is ScanEventType.COMPLETED
    assert len(fake_conversion) == 4


@pytest.mark.asyncio
async def test_scan_cancels_between_documents_and_keeps_converted_in_cache(tmp_path: Path, source: Path, fake_conversion: list[str]) -> None:
    layout = ProjectLayout(tmp_path / "p")
    token = CancelToken()

    def _cancel_after_two(event: ProgressEvent) -> None:
        if event.phase == "conversion" and event.processed == 2 and event.current is None:
            token.cancel()

    events = [event async for event in _scan(layout, source, on_progress=_cancel_after_two, cancel_token=token)]

    assert events[-1].event is ScanEventType.CANCELLED
    assert not any(event.event is ScanEventType.COMPLETED for event in events)
    assert len(fake_conversion) == 2  # el tercero no empieza
    async with CacheManager(layout.cache_db) as cache:
        assert len(await cache.load_cache()) == 2  # lo convertido no se pierde
    runs = list_scan_runs(layout.scan_history_log)
    assert [run.completed for run in runs] == [False]

    # Un escaneo posterior continúa: solo convierte los que faltaban.
    fake_conversion.clear()
    events = [event async for event in _scan(layout, source)]
    assert events[-1].event is ScanEventType.COMPLETED
    assert len(fake_conversion) == 2


@pytest.mark.asyncio
async def test_run_raises_when_cancelled(tmp_path: Path, source: Path, fake_conversion: list[str]) -> None:
    token = CancelToken()
    token.cancel()
    layout = ProjectLayout(tmp_path / "p")

    with pytest.raises(OperationCancelledError):
        await ScanCommand().run(
            paths=[str(source)],
            output_dir=layout.conversion_dir,
            cache_db=layout.cache_db,
            folders_json=layout.folders_json,
            options=ScanOptions(use_ocr=False),
            cancel_token=token,
        )
    assert fake_conversion == []


@pytest.mark.asyncio
async def test_dedup_cancels_between_groups(tmp_path: Path) -> None:
    folder = tmp_path / "origen"
    folder.mkdir()
    for index in range(3):
        (folder / f"grupo{index}_a.pdf").write_bytes(PDF + str(index).encode())
        (folder / f"grupo{index}_b.pdf").write_bytes(PDF + str(index).encode())
    layout = ProjectLayout(tmp_path / "p")
    token = CancelToken()
    progress: list[ProgressEvent] = []

    def _track(event: ProgressEvent) -> None:
        progress.append(event)
        if event.processed == 1 and event.phase == "deduplication":
            token.cancel()

    events = [
        event
        async for event in ScanCommand().deduplicate_streaming(
            [str(folder)], layout.duplicates_dir, layout.folders_json, on_progress=_track, cancel_token=token
        )
    ]

    assert events[-1].event is DedupEventType.CANCELLED
    assert sum(1 for e in events if e.event is DedupEventType.GROUP_RESOLVED) == 1
    assert layout.dedup_report.exists()  # el informe recoge lo movido hasta la parada
    assert progress[0].operation == "deduplicate"


@pytest.mark.asyncio
async def test_context_build_cancelled_before_start_persists_nothing(tmp_path: Path) -> None:
    project = Project(name="P", root_path=str(tmp_path), created_at="2026-10-31T00:00:00+00:00")
    token = CancelToken()
    token.cancel()

    with pytest.raises(OperationCancelledError):
        await ContextBuilder().build(project, [], cancel_token=token)

    assert not (tmp_path / "context.json").exists()
