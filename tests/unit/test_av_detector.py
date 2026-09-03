"""Tests unitarios de detect_av_status (menú Escaneo: detección de entorno audio/vídeo).

Mismo patrón que `test_gpu_detector.py`.
"""

import subprocess

import pytest

from doc_organize.utils import av_detector


@pytest.fixture(autouse=True)
def _clear_cache():
    av_detector.detect_av_status.cache_clear()
    yield
    av_detector.detect_av_status.cache_clear()


def test_is_ffmpeg_available_returns_true_when_which_finds_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cuando shutil.which encuentra ffmpeg, _is_ffmpeg_available retorna True."""
    monkeypatch.setattr(av_detector.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    result = av_detector._is_ffmpeg_available()

    assert result is True


def test_is_ffmpeg_available_fallback_to_subprocess_when_which_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cuando shutil.which falla, intenta ejecutar ffmpeg directamente."""
    monkeypatch.setattr(av_detector.shutil, "which", lambda name: None)

    def mock_run(*args, **kwargs):
        # Simular una ejecución exitosa de ffmpeg
        return None

    monkeypatch.setattr(av_detector.subprocess, "run", mock_run)

    result = av_detector._is_ffmpeg_available()

    assert result is True


def test_is_ffmpeg_available_returns_false_when_neither_method_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cuando ni which ni subprocess encuentran ffmpeg, retorna False."""
    monkeypatch.setattr(av_detector.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        av_detector.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("ffmpeg not found")),
    )

    result = av_detector._is_ffmpeg_available()

    assert result is False


def test_is_ffmpeg_available_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cuando subprocess.run se agota el timeout, retorna False."""
    monkeypatch.setattr(av_detector.shutil, "which", lambda name: None)

    def mock_run_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", 2)

    monkeypatch.setattr(av_detector.subprocess, "run", mock_run_timeout)

    result = av_detector._is_ffmpeg_available()

    assert result is False


def test_nothing_installed_reports_both_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(av_detector, "find_spec", lambda name: None)
    monkeypatch.setattr(av_detector, "_is_ffmpeg_available", lambda: False)

    status = av_detector.detect_av_status()

    assert status.asr_installed is False
    assert status.ffmpeg_installed is False
    assert status.ready is False
    assert status.instructions is not None
    assert "av" in status.instructions
    assert "ffmpeg" in status.instructions


def test_only_asr_missing_reports_asr_specific_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(av_detector, "find_spec", lambda name: None)
    monkeypatch.setattr(av_detector, "_is_ffmpeg_available", lambda: True)

    status = av_detector.detect_av_status()

    assert status.asr_installed is False
    assert status.ffmpeg_installed is True
    assert status.ready is False
    assert status.instructions is not None
    assert "av" in status.instructions
    assert "ffmpeg" not in status.instructions


def test_only_ffmpeg_missing_reports_ffmpeg_specific_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(av_detector, "find_spec", lambda name: object())
    monkeypatch.setattr(av_detector, "_is_ffmpeg_available", lambda: False)

    status = av_detector.detect_av_status()

    assert status.asr_installed is True
    assert status.ffmpeg_installed is False
    assert status.ready is False
    assert status.instructions is not None
    assert "ffmpeg" in status.instructions
    assert "pip install" not in status.instructions


def test_both_installed_reports_ready_without_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(av_detector, "find_spec", lambda name: object())
    monkeypatch.setattr(av_detector, "_is_ffmpeg_available", lambda: True)

    status = av_detector.detect_av_status()

    assert status.asr_installed is True
    assert status.ffmpeg_installed is True
    assert status.ready is True
    assert status.instructions is None


def test_result_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _counting_find_spec(name: str) -> object | None:
        calls["count"] += 1
        return None

    monkeypatch.setattr(av_detector, "find_spec", _counting_find_spec)
    monkeypatch.setattr(av_detector, "_is_ffmpeg_available", lambda: False)

    av_detector.detect_av_status()
    av_detector.detect_av_status()

    assert calls["count"] == 1
