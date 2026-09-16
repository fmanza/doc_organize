"""Tests unitarios de detect_office_status (menú Escaneo: deteccion de LibreOffice para .xls).

Mismo patron que `test_gpu_detector.py`/`test_av_detector.py`.
"""

import pytest

from doc_organize.utils import office_detector


@pytest.fixture(autouse=True)
def _clear_cache():
    office_detector.detect_office_status.cache_clear()
    yield
    office_detector.detect_office_status.cache_clear()


def test_libreoffice_missing_reports_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office_detector.shutil, "which", lambda name: None)

    status = office_detector.detect_office_status()

    assert status.libreoffice_installed is False
    assert status.instructions is not None
    assert "LibreOffice" in status.instructions


def test_libreoffice_found_as_libreoffice_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office_detector.shutil, "which", lambda name: "/usr/bin/libreoffice" if name == "libreoffice" else None)

    status = office_detector.detect_office_status()

    assert status.libreoffice_installed is True
    assert status.instructions is None


def test_libreoffice_found_as_soffice_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office_detector.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None)

    status = office_detector.detect_office_status()

    assert status.libreoffice_installed is True
    assert status.instructions is None


def test_result_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _counting_which(name: str) -> str | None:
        calls["count"] += 1
        return None

    monkeypatch.setattr(office_detector.shutil, "which", _counting_which)

    office_detector.detect_office_status()
    office_detector.detect_office_status()

    # 2 shutil.which por llamada real (libreoffice, soffice); la 2a
    # invocacion de detect_office_status() se sirve del lru_cache, sin
    # llamadas nuevas.
    assert calls["count"] == 2
