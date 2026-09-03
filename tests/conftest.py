"""Configuración de pytest."""

import os
import shutil
import sys
import tempfile

from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_SAMPLE_TEXT = "Informe de prueba doc_organize\n\nDocumento de fixture para tests de conversion y deteccion de OCR.\nFecha: 2026-08-27."


@pytest.fixture(autouse=True, scope="session")
def _isolate_doc_organize_logs():
    """Evita que `configure_logging()` (invocada por `main()`, p. ej. desde
    `test_main.py`) escriba `logs/doc_organize.log` dentro del propio repositorio:
    fija `DOC_ORGANIZE_LOG_DIR` a una carpeta temporal antes de que arranque
    cualquier test, para toda la sesión de pytest — `configure_logging()` solo se
    ejecuta de verdad una vez por proceso (es idempotente), así que basta con
    fijar la variable de entorno antes de esa primera llamada, la que sea.

    `mkdtemp` (no `TemporaryDirectory`, que borraría la carpeta al salir del
    `with`): el `TimedRotatingFileHandler` real que instala `configure_logging()`
    mantiene `doc_organize.log` abierto durante toda la sesión de pytest (nunca se
    cierra, es un logger de proceso) — en Windows, borrar una carpeta con un
    fichero todavía abierto lanza `PermissionError`. `ignore_errors=True` hace el
    intento de limpieza best-effort en vez de fallar la sesión de tests por esto;
    la carpeta huérfana ocasional queda bajo el directorio temporal del sistema,
    no en el repositorio.
    """
    tmp_dir = tempfile.mkdtemp(prefix="doc_organize_test_logs_")
    previous = os.environ.get("DOC_ORGANIZE_LOG_DIR")
    os.environ["DOC_ORGANIZE_LOG_DIR"] = tmp_dir
    yield
    if previous is None:
        os.environ.pop("DOC_ORGANIZE_LOG_DIR", None)
    else:
        os.environ["DOC_ORGANIZE_LOG_DIR"] = previous
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def native_pdf(tmp_path: Path) -> Path:
    """PDF con una capa de texto real embebida (via matplotlib)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = tmp_path / "native.pdf"
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.1, 0.7, _SAMPLE_TEXT, fontsize=14, family="sans-serif")
    fig.savefig(path, format="pdf")
    plt.close(fig)
    return path


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    """PDF sin capa de texto: una imagen renderizada con texto, envuelta en PDF."""
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path / "scanned.pdf"
    img = Image.new("RGB", (1240, 1754), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.multiline_text((80, 200), _SAMPLE_TEXT, fill="black", font=font, spacing=12)
    img.save(path, "PDF", resolution=150.0)
    return path
