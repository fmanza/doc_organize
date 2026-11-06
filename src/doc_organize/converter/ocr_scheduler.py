"""
Deteccion y procesamiento de OCR en dos fases (REQ-004).
"""

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Literal

from doc_organize.converter.converter import DocumentConverter
from doc_organize.core.models import ConversionResult, DocumentMetadata
from doc_organize.core.progress import CancelToken
from doc_organize.utils.logging import get_logger
from doc_organize.utils.memory import MemoryReleaser, release_memory


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

    `artifacts_path` y `allow_model_downloads` se pasan al `DocumentConverter` del lote (L-10b, ver su docstring).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def main():
        ...     scheduler = OCRScheduler()
        ...     results = await scheduler.process_with_ocr(candidates, Path("./Conversión"))
        >>> asyncio.run(main())  # doctest: +SKIP
    """

    # +SKIP deliberado (AUDIT_CODE, sesión 2026-09-03/04): `process_with_ocr()`
    # necesita un documento real con OCR real de Docling (carga de modelo
    # incluida) -- mismo motivo que `DocumentConverter.convert_document()`, ver
    # su docstring. `test_ocr_scheduler.py` ya cubre esto de verdad, marcado
    # `@pytest.mark.slow`.

    def __init__(self, *, artifacts_path: Path | str | None = None, allow_model_downloads: bool = True) -> None:
        self.logger = get_logger(__name__)
        self._artifacts_path = artifacts_path
        self._allow_model_downloads = allow_model_downloads

    async def process_with_ocr(
        self,
        docs: list[DocumentMetadata],
        output_dir: Path,
        use_gpu: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
        scan_roots: Sequence[str] = (),
        progress_callback: Callable[[DocumentMetadata, int, int], Awaitable[None]] | None = None,
        *,
        include_root_name: bool = False,
        json_source_path: Literal["relative", "absolute"] = "relative",
        timeout_s: float | None = None,
        cancel_token: CancelToken | None = None,
        max_documents: int | None = None,
    ) -> list[ConversionResult]:
        """Reconvierte `docs` con OCR activado y escribe los resultados en `output_dir`.

        `extract_images`/`use_picture_description` se propagan tal cual a
        `DocumentConverter.convert_document()` (mismo significado que en la
        primera pasada, ver `ScanCommand._convert_documents`): un documento que
        solo se resuelve en esta segunda pasada (porque necesitaba OCR) no debe
        quedarse sin imagenes/descripciones solo por haber requerido OCR. Mismo
        motivo para `scan_roots`: debe ser el mismo usado en la primera pasada
        para que ambas calculen la misma ruta de salida (`resolve_output_paths`)
        para un mismo documento.

        Nota de IMPLEMENT: `output_dir` se añadió a este método porque
        `DocumentConverter.convert_document()` lo necesita para saber dónde
        escribir la salida; el pseudocódigo original del plan (§2.4) no lo
        incluía.

        Args:
            progress_callback: si se indica, se invoca `await progress_callback(doc,
                index, total)` (índice 1-based) justo antes de reconvertir cada
                documento. Permite a quien orquesta el batch (`ScanCommand._process_ocr`)
                informar progreso en vivo sin que este método conozca `ScanEvent`/
                WebSocket -- mantiene la capa de OCR agnóstica del transporte de eventos.
            include_root_name: igual que en `DocumentConverter.convert_document` (L-10c);
                debe coincidir con la primera pasada.
            json_source_path: igual que en `DocumentConverter.convert_document` (G23).
            timeout_s: limite por documento, igual que en `DocumentConverter.convert_document` (G11, 1.1.0).
            cancel_token: si se cancela, para **entre documentos** sin lanzar excepcion (G38, 1.1.0): el documento en
                curso termina y se devuelven los resultados de los ya procesados.
            max_documents: procesa como mucho estos documentos (G38, 1.1.0); `None`, todos.

        Returns:
            Un `ConversionResult` por documento procesado, en el orden de `docs`. Con `cancel_token` o
            `max_documents` puede tener menos elementos que `docs`: los que faltan son los del final, sin procesar.
        """
        results: list[ConversionResult] = []
        total = len(docs)
        extra: dict[str, float] = {"timeout_s": timeout_s} if timeout_s is not None else {}
        releaser = MemoryReleaser()  # G38: los ciclos que deja cada documento se liberan cada pocos documentos
        async with DocumentConverter(artifacts_path=self._artifacts_path, allow_model_downloads=self._allow_model_downloads) as converter:
            for index, doc in enumerate(docs, start=1):
                if cancel_token is not None and cancel_token.cancelled:
                    self.logger.info(f"OCR cancelado tras {index - 1} de {total} documentos")
                    break
                if max_documents is not None and index > max_documents:
                    break
                if progress_callback is not None:
                    await progress_callback(doc, index, total)
                result = await converter.convert_document(
                    doc,
                    output_dir,
                    use_ocr=True,
                    use_gpu=use_gpu,
                    extract_images=extract_images,
                    use_picture_description=use_picture_description,
                    scan_roots=scan_roots,
                    include_root_name=include_root_name,
                    json_source_path=json_source_path,
                    **extra,
                )
                results.append(result)
                releaser.after_document()
        release_memory()

        succeeded = sum(1 for result in results if result.success)
        self.logger.info(f"OCR procesado: {succeeded}/{len(results)} documentos convertidos correctamente ({total} candidatos)")
        return results


__all__ = ["OCRScheduler"]
