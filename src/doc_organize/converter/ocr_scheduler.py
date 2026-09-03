"""
Deteccion y procesamiento de OCR en dos fases (REQ-004).
"""

from pathlib import Path

from doc_organize.converter.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, DocumentMetadata
from doc_organize.utils.logging import get_logger


class OCRScheduler:
    """Reprocesa con OCR los documentos que lo necesitan.

    La detección de qué documentos necesitan OCR no vive aquí: ocurre gratis
    durante la conversión normal de `ScanCommand` (`DocumentConverter._needs_ocr()`
    sobre `result.confidence.parse_score` siendo `NaN`, señal confirmada por spike
    2026-08-27, ver plan §2.4), que ya marca cada `ConversionResult.ocr_required`
    en su única pasada de conversión. `process_with_ocr()` reconvierte esos
    documentos con OCR activado; `use_gpu` solo selecciona un motor acelerado
    (EasyOCR) en vez del motor CPU por defecto (RapidOCR) — no es un requisito
    funcional, es una optimizacion de velocidad (AUDIT_PLAN revision 5).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def main():
        ...     scheduler = OCRScheduler()
        ...     results = await scheduler.process_with_ocr(candidates, Path("./Conversión"))
        >>> asyncio.run(main())
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    async def process_with_ocr(
        self,
        docs: list[DocumentMetadata],
        output_dir: Path,
        use_gpu: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
    ) -> list[ConversionResult]:
        """Reconvierte `docs` con OCR activado y escribe los resultados en `output_dir`.

        `extract_images`/`use_picture_description` se propagan tal cual a
        `DocumentConverter.convert_document()` (mismo significado que en la
        primera pasada, ver `ScanCommand._convert_documents`): un documento que
        solo se resuelve en esta segunda pasada (porque necesitaba OCR) no debe
        quedarse sin imagenes/descripciones solo por haber requerido OCR.

        Nota de IMPLEMENT: `output_dir` se añadió a este método porque
        `DocumentConverter.convert_document()` lo necesita para saber dónde
        escribir la salida; el pseudocódigo original del plan (§2.4) no lo
        incluía.
        """
        results: list[ConversionResult] = []
        async with DocumentConverter() as converter:
            for doc in docs:
                result = await converter.convert_document(
                    doc,
                    output_dir,
                    use_ocr=True,
                    use_gpu=use_gpu,
                    extract_images=extract_images,
                    use_picture_description=use_picture_description,
                )
                results.append(result)

        succeeded = sum(1 for result in results if result.success)
        self.logger.info(f"OCR procesado: {succeeded}/{len(docs)} documentos convertidos correctamente")
        return results


__all__ = ["OCRScheduler"]
