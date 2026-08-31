"""Tests unitarios de detect_gpu_status (menú Escaneo: detección de entorno GPU)."""

import sys

import pytest

from doc_organize.utils import gpu_detector


@pytest.fixture(autouse=True)
def _clear_cache():
    gpu_detector.detect_gpu_status.cache_clear()
    yield
    gpu_detector.detect_gpu_status.cache_clear()


def test_no_torch_installed_reports_no_support(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_detector, "find_spec", lambda name: None)

    status = gpu_detector.detect_gpu_status()

    assert status.gpu_support_installed is False
    assert status.gpu_active is False
    assert status.instructions is not None
    assert "ocr-gpu" in status.instructions


def test_torch_installed_without_active_cuda_reports_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = _fake_torch(cuda_available=False)
    monkeypatch.setattr(gpu_detector, "find_spec", lambda name: object())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    status = gpu_detector.detect_gpu_status()

    assert status.gpu_support_installed is True
    assert status.gpu_active is False
    assert status.instructions is not None
    assert "drivers" in status.instructions.lower()


def test_torch_installed_with_active_cuda_reports_no_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = _fake_torch(cuda_available=True)
    monkeypatch.setattr(gpu_detector, "find_spec", lambda name: object())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    status = gpu_detector.detect_gpu_status()

    assert status.gpu_support_installed is True
    assert status.gpu_active is True
    assert status.instructions is None


def test_result_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _counting_find_spec(name: str) -> object | None:
        calls["count"] += 1
        return None

    monkeypatch.setattr(gpu_detector, "find_spec", _counting_find_spec)

    gpu_detector.detect_gpu_status()
    gpu_detector.detect_gpu_status()

    assert calls["count"] == 1


def _fake_torch(*, cuda_available: bool):
    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return cuda_available

    class _Torch:
        cuda = _Cuda()

    return _Torch()
