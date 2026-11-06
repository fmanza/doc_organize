"""Medida de la memoria de un escaneo largo con OCR (G38 / L-16, 1.1.0). Fuera del CI.

Genera N documentos sintéticos (PDF con texto, PDF escaneado, .docx, .xlsx y .html a partes iguales), los escanea con
OCR y Docling real y anota el RSS del proceso cada 50 conversiones (primera pasada y OCR cuentan por separado). No
falla por crecer: deja las medidas en un JSON para comparar versiones o entornos.

    DOC_ORGANIZE_MEMORY_TEST=1 python -m pytest tests/integration/test_scan_memory_growth.py -s --no-cov

Variables: `DOC_ORGANIZE_MEMORY_DOCS` (documentos, 200 por defecto) y `DOC_ORGANIZE_MEMORY_REPORT` (ruta del JSON; por
defecto `memory_report.json` en la carpeta temporal del test). Resultados de referencia en
`docs/guides/troubleshooting.md` («Memoria en escaneos largos»).
"""

import json
import os
import platform
import sys
import time

from pathlib import Path

import pytest

from doc_organize import ScanCommand, ScanOptions
from doc_organize.core.models import ScanEventType

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("DOC_ORGANIZE_MEMORY_TEST") != "1", reason="medida larga: DOC_ORGANIZE_MEMORY_TEST=1"),
]

_SAMPLE_EVERY = 50


def _rss_mib() -> float:
    try:
        import psutil
    except ImportError:
        with open("/proc/self/statm", encoding="ascii") as statm:  # Linux sin psutil
            return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1_048_576
    return float(psutil.Process().memory_info().rss) / 1_048_576


def _make_documents(folder: Path, count: int) -> None:
    import docx
    import matplotlib
    import openpyxl

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except OSError:
        font = ImageFont.load_default()
    for index in range(count):
        text = f"Documento sintético {index}\n\nInforme de prueba número {index} para medir la memoria.\nImporte: {index * 7} EUR"
        kind = index % 5
        if kind == 0:
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.1, 0.7, text, fontsize=14)
            fig.savefig(folder / f"nativo_{index:04d}.pdf", format="pdf")
            plt.close(fig)
        elif kind == 1:
            image = Image.new("RGB", (1240, 1754), color="white")
            ImageDraw.Draw(image).multiline_text((80, 200), text, fill="black", font=font, spacing=12)
            image.save(folder / f"escaneado_{index:04d}.pdf", "PDF", resolution=150.0)
        elif kind == 2:
            document = docx.Document()
            document.add_heading(f"Informe {index}", level=1)
            for line in text.splitlines():
                document.add_paragraph(line)
            document.save(str(folder / f"word_{index:04d}.docx"))
        elif kind == 3:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(["Concepto", "Importe"])
            for row in range(20):
                sheet.append([f"Línea {row} del documento {index}", row * index])
            workbook.save(folder / f"excel_{index:04d}.xlsx")
        else:
            body = "".join(f"<p>{line}</p>" for line in text.splitlines())
            (folder / f"pagina_{index:04d}.html").write_text(f"<html><body><h1>Página {index}</h1>{body}</body></html>", encoding="utf-8")


@pytest.mark.asyncio
async def test_scan_memory_growth_report(tmp_path: Path) -> None:
    count = int(os.environ.get("DOC_ORGANIZE_MEMORY_DOCS", "200"))
    report_path = Path(os.environ.get("DOC_ORGANIZE_MEMORY_REPORT", str(tmp_path / "memory_report.json")))
    source = tmp_path / "origen"
    source.mkdir()
    _make_documents(source, count)
    project = tmp_path / "proyecto"

    samples: list[dict[str, float | int | str]] = []
    conversions = 0
    start = time.monotonic()

    def _sample(label: str) -> None:
        samples.append({"conversions": conversions, "rss_mib": round(_rss_mib(), 1), "seconds": round(time.monotonic() - start, 1), "at": label})

    _sample("inicio")
    async for event in ScanCommand().run_streaming(
        paths=[str(source)],
        output_dir=project / "Conversión",
        cache_db=project / "cache.db",
        folders_json=project / "folders.json",
        options=ScanOptions(use_ocr=True, use_gpu=False),
    ):
        if event.event in (ScanEventType.FILE_CONVERTED, ScanEventType.OCR_PROCESSED):
            conversions += 1
            if conversions % _SAMPLE_EVERY == 0:
                _sample(event.event.value)
        elif event.event is ScanEventType.OCR_STARTED:
            _sample("ocr_started")
        elif event.event is ScanEventType.COMPLETED:
            _sample("completed")
            summary = event.data

    report = {
        "documents": count,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "summary": summary,
        "samples": samples,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(samples, indent=1))

    assert summary["converted"] == count
