"""
Conversion de documentos a Markdown + JSON via Docling (REQ-003).
"""

import asyncio
import json
import math
import time

from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter as DoclingConverter, PdfFormatOption

from doc_organize.core.exceptions import ConversionError
from doc_organize.core.models import ConversionResult, DocumentMetadata
from doc_organize.utils.logging import get_logger


class DocumentConverter:
    """Convierte documentos a Markdown + JSON usando Docling (REQ-003).

    Guarda salida dual (`<nombre>.md` + `<nombre>.json`) manteniendo la
    estructura de directorios original bajo `output_dir`. Los errores de
    conversion se capturan y se devuelven en `ConversionResult.error`, sin
    interrumpir el resto de un batch (responsabilidad del llamante).

    La deteccion de `ocr_required` (REQ-004) se basa en
    `result.confidence.parse_score` siendo `NaN` — señal confirmada
    empiricamente con un spike real (ver `doclink_extractor_plan.md` §2.4):
    un documento sin capa de texto nativa no tiene `parse_score`, tenga o
    no OCR aplicado en esa misma pasada.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def main():
        ...     async with DocumentConverter() as converter:
        ...         result = await converter.convert_document(doc, Path("./Conversión"))
        >>> asyncio.run(main())
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._docling_by_mode: dict[tuple[bool, bool], DoclingConverter] | None = None

    async def __aenter__(self) -> "DocumentConverter":
        self._docling_by_mode = {}
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._docling_by_mode = None

    def _get_docling(self, use_ocr: bool, use_gpu: bool = False) -> DoclingConverter:
        if self._docling_by_mode is None:
            raise ConversionError("DocumentConverter debe usarse como context manager async ('async with').")

        key = (use_ocr, use_gpu)
        if key not in self._docling_by_mode:
            options = PdfPipelineOptions()
            options.do_ocr = use_ocr
            if use_ocr and use_gpu:
                # RapidOCR (default, via onnxruntime) es CPU-only. EasyOCR soporta
                # aceleracion GPU (torch/cuda) — se activa solo si el llamante lo pide
                # explicitamente; no es un requisito para que el OCR funcione (AUDIT_PLAN rev. 5).
                options.ocr_options = EasyOcrOptions(use_gpu=True)
            self._docling_by_mode[key] = DoclingConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
        return self._docling_by_mode[key]

    async def probe_needs_ocr(self, source_path: str) -> bool:
        """Determina si `source_path` necesita OCR, sin escribir ningun archivo.

        Ejecuta una conversion rapida con `do_ocr=False` y comprueba si el
        documento tiene capa de texto nativa (usado por `OCRScheduler`, REQ-004).
        """
        docling_result = await asyncio.to_thread(self._get_docling(use_ocr=False).convert, source_path)
        return self._needs_ocr(docling_result)

    async def convert_document(
        self,
        source_doc: DocumentMetadata,
        output_dir: Path,
        use_ocr: bool = False,
        use_gpu: bool = False,
    ) -> ConversionResult:
        """Convierte `source_doc` a Markdown + JSON bajo `output_dir`.

        Args:
            source_doc: Metadata del documento a convertir (ya escaneado y con hash).
            output_dir: Carpeta raiz de salida (`Conversión/`); se replica la
                estructura de directorios original del documento debajo de ella.
            use_ocr: Si `True`, activa OCR en Docling para este documento.
            use_gpu: Si `True` (y `use_ocr=True`), usa un motor OCR acelerado
                por GPU (EasyOCR) en vez del motor CPU por defecto (RapidOCR).

        Returns:
            ConversionResult con las rutas de salida, si tuvo exito, y si el
            documento requiere OCR (para REQ-004).
        """
        start = time.monotonic()
        output_dir = Path(output_dir)
        # _get_docling() valida el uso como context manager; ese error de programacion
        # se propaga (no se atrapa como fallo de conversion de este documento).
        docling_converter = self._get_docling(use_ocr, use_gpu)

        try:
            docling_result = await asyncio.to_thread(docling_converter.convert, source_doc.full_path)
        # Excepcion amplia deliberada: cualquier fallo de conversion se reporta en
        # ConversionResult (success=False), nunca se relanza.
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"Error convirtiendo '{source_doc.full_path}': {exc}")
            return ConversionResult(
                source_path=source_doc.full_path,
                markdown_path=None,
                json_path=None,
                success=False,
                error=str(exc),
                ocr_required=False,
                duration_seconds=time.monotonic() - start,
            )

        ocr_required = self._needs_ocr(docling_result)
        markdown_path, json_path = await self._write_outputs(source_doc, docling_result, output_dir, ocr_required)

        duration = time.monotonic() - start
        self.logger.info(f"Convertido '{source_doc.full_path}' en {duration:.2f}s (ocr_required={ocr_required})")
        return ConversionResult(
            source_path=source_doc.full_path,
            markdown_path=str(markdown_path),
            json_path=str(json_path),
            success=True,
            error=None,
            ocr_required=ocr_required,
            duration_seconds=duration,
        )

    async def _write_outputs(
        self,
        source_doc: DocumentMetadata,
        docling_result: Any,
        output_dir: Path,
        ocr_required: bool,
    ) -> tuple[Path, Path]:
        markdown_text = docling_result.document.export_to_markdown()

        relative_parts = Path(source_doc.full_path).resolve().parts[1:]
        stem = Path(relative_parts[-1]).stem if relative_parts else Path(source_doc.full_path).stem
        target_dir = output_dir.joinpath(*relative_parts[:-1]) if len(relative_parts) > 1 else output_dir
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)

        markdown_path = target_dir / f"{stem}.md"
        json_path = target_dir / f"{stem}.json"

        metadata = {
            "source_path": source_doc.full_path,
            "title": stem,
            "size_bytes": source_doc.size_bytes,
            "sha256_hash": source_doc.sha256_hash,
            "modified_time": source_doc.modified_time,
            "ocr_required": ocr_required,
        }

        await asyncio.to_thread(markdown_path.write_text, markdown_text, encoding="utf-8")
        await asyncio.to_thread(json_path.write_text, json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return markdown_path, json_path

    @staticmethod
    def _needs_ocr(docling_result: Any) -> bool:
        """`True` si el documento no tiene capa de texto nativa (`parse_score`
        es `NaN`) — señal confirmada empiricamente en el spike de REQ-004."""
        parse_score = docling_result.confidence.parse_score
        return math.isnan(parse_score)


__all__ = ["DocumentConverter"]
