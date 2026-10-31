"""API pública (L-1, G1, G15): ``__all__`` resoluble, versión de los metadatos e importación ligera."""

import subprocess
import sys

from importlib.metadata import version
from pathlib import Path

import pytest

import doc_organize


def test_every_public_name_resolves() -> None:
    missing = [name for name in doc_organize.__all__ if not hasattr(doc_organize, name)]

    assert missing == []


def test_version_comes_from_package_metadata() -> None:
    assert doc_organize.__version__ == version("doc_organize")


def test_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no_existe"):
        doc_organize.no_existe  # noqa: B018 - se comprueba el error de acceso


def test_py_typed_marker_is_shipped() -> None:
    assert (Path(doc_organize.__file__).parent / "py.typed").is_file()


def test_importing_package_and_light_modules_does_not_load_docling() -> None:
    """Un consumidor (doc_organize_web) puede leer versión, modelos y diagnósticos sin cargar Docling ni torch."""
    code = (
        "import sys, doc_organize, doc_organize.core.models, doc_organize.core.exceptions, "
        "doc_organize.utils.gpu_detector, doc_organize.utils.av_detector, doc_organize.utils.office_detector; "
        "from doc_organize import ScanEvent, Project, detect_office_status; "
        "print(sorted(m for m in ('docling', 'torch') if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120)

    assert result.stdout.strip() == "[]"
