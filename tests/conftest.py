"""Configuración de pytest."""

import sys

from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_SAMPLE_TEXT = "Informe de prueba doc_organize\n\nDocumento de fixture para tests de conversion y deteccion de OCR.\nFecha: 2026-08-27."


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
