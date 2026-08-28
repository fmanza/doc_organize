"""
Deteccion y procesamiento de OCR en dos fases (REQ-004).
"""

from pathlib import Path

from doc_organize.converter.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, DocumentMetadata
from doc_organize.utils.logging import get_logger


class OCRScheduler:
    """Detecta que documentos necesitan OCR y los reprocesa en una segunda pasada.

    `detect_ocr_candidates()` usa `DocumentConverter.probe_needs_ocr()` (una
    pasada rapida con `do_ocr=False`, sin escribir archivos) apoyandose en la
    señal confirmada por spike (2026-08-27, ver plan §2.4):
    `result.confidence.parse_score` es `NaN` cuando el documento no tiene
    capa de texto nativa. `process_with_ocr()` reconvierte esos documentos
    con OCR activado; `use_gpu` solo selecciona un motor acelerado (EasyOCR)
    en vez del motor CPU por defecto (RapidOCR) — no es un requisito
    funcional, es una optimizacion de velocidad (AUDIT_PLAN revision 5).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def main():
        ...     scheduler = OCRScheduler()
        ...     candidates = await scheduler.detect_ocr_candidates(docs)
        ...     results = await scheduler.process_with_ocr(candidates, Path("./Conversión"))
        >>> asyncio.run(main())
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    async def detect_ocr_candidates(self, docs: list[DocumentMetadata]) -> list[DocumentMetadata]:
        """Identifica, sin escribir ningun archivo, que documentos de `docs`
        no tienen capa de texto nativa y por tanto requieren OCR."""
        candidates: list[DocumentMetadata] = []
        async with DocumentConverter() as converter:
            for doc in docs:
                if await converter.probe_needs_ocr(doc.full_path):
                    candidates.append(doc)

        self.logger.info(f"OCR: {len(candidates)} de {len(docs)} documentos requieren OCR")
        return candidates

    async def process_with_ocr(
        self,
        docs: list[DocumentMetadata],
        output_dir: Path,
        use_gpu: bool = False,
    ) -> list[ConversionResult]:
        """Reconvierte `docs` con OCR activado y escribe los resultados en `output_dir`.

        Nota de IMPLEMENT: `output_dir` se añadió a este método porque
        `DocumentConverter.convert_document()` lo necesita para saber dónde
        escribir la salida; el pseudocódigo original del plan (§2.4) no lo
        incluía.
        """
        results: list[ConversionResult] = []
        async with DocumentConverter() as converter:
            for doc in docs:
                result = await converter.convert_document(doc, output_dir, use_ocr=True, use_gpu=use_gpu)
                results.append(result)

        succeeded = sum(1 for result in results if result.success)
        self.logger.info(f"OCR procesado: {succeeded}/{len(docs)} documentos convertidos correctamente")
        return results


__all__ = ["OCRScheduler"]
