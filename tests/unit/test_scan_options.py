"""`ScanOptions` (G13): opciones del escaneo en un modelo en lugar de indicadores posicionales."""

import pytest

from pydantic import ValidationError

from doc_organize import ScanCommand, ScanOptions
from doc_organize.core.models import ScanEventType
from doc_organize.scan.scan_command import resolve_scan_options

LOOSE_DEFAULTS = {
    "force": False,
    "include_audio_video": False,
    "extract_images": False,
    "use_picture_description": False,
}


def test_options_are_immutable_and_reject_unknown_fields() -> None:
    options = ScanOptions(use_ocr=False, extract_images=True)

    assert (options.use_ocr, options.use_gpu, options.extract_images) == (False, False, True)
    with pytest.raises(ValidationError):
        ScanOptions(usar_ocr=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        options.use_gpu = True  # type: ignore[misc]


def test_resolve_prefers_options() -> None:
    options = ScanOptions(use_gpu=True)

    assert resolve_scan_options(options, use_ocr=None, use_gpu=None, **LOOSE_DEFAULTS) is options


def test_resolve_builds_options_from_loose_flags() -> None:
    resolved = resolve_scan_options(None, use_ocr=True, use_gpu=False, **{**LOOSE_DEFAULTS, "force": True})

    assert resolved == ScanOptions(use_ocr=True, use_gpu=False, force=True)


@pytest.mark.parametrize(
    ("use_ocr", "loose"),
    [(True, LOOSE_DEFAULTS), (None, {**LOOSE_DEFAULTS, "force": True})],
)
def test_resolve_rejects_mixing_options_and_flags(use_ocr: bool | None, loose: dict[str, bool]) -> None:
    with pytest.raises(TypeError, match="no de las dos formas"):
        resolve_scan_options(ScanOptions(), use_ocr=use_ocr, use_gpu=None, **loose)


def test_resolve_requires_ocr_and_gpu_without_options() -> None:
    with pytest.raises(TypeError, match="options=ScanOptions"):
        resolve_scan_options(None, use_ocr=True, use_gpu=None, **LOOSE_DEFAULTS)


@pytest.mark.asyncio
async def test_run_streaming_accepts_options(tmp_path) -> None:
    source = tmp_path / "origen"
    source.mkdir()

    events = [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(source)],
            output_dir=tmp_path / "salida",
            cache_db=tmp_path / "estado" / "cache.db",
            folders_json=tmp_path / "estado" / "folders.json",
            options=ScanOptions(use_ocr=False),
        )
    ]

    assert events[-1].event is ScanEventType.COMPLETED
