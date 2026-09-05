"""
Conversion de documentos a Markdown + JSON via Docling (REQ-003).
"""

import asyncio
import json
import math
import shutil
import time

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self, cast

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions, smolvlm_picture_description
from docling.document_converter import DocumentConverter as DoclingConverter, ImageFormatOption, PdfFormatOption
from docling_core.transforms.chunker.doc_chunk import DocChunk
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.items.node import DocItem
from docling_core.types.doc.items.picture.picture import PictureDescriptionData, PictureItem

from doc_organize.core.exceptions import ConversionError
from doc_organize.core.models import ConversionResult, DocumentMetadata
from doc_organize.utils.logging import get_logger


class DocumentConverter:
    """Convierte documentos a Markdown + JSON usando Docling (REQ-003).

    Guarda salida dual (`<nombre>.md` + `<nombre>.json`) manteniendo la
    estructura de directorios original bajo `output_dir`. El `.json` esta
    pensado para consumo por IA (RAG/embeddings), no como export de layout:
    en vez del arbol completo de Docling (con bounding boxes, coordenadas y
    referencias internas — ruido de formato irrelevante para un LLM), usa
    `HierarchicalChunker` (sin dependencias de tokenizer/descarga de modelo)
    para trocear el documento en chunks por seccion, cada uno con su texto,
    la ruta de encabezados (`headings`) y las paginas de origen. La metadata
    propia de doc_organize (hash, tamano, fecha, ocr_required) va en el nivel
    raiz del mismo fichero, junto a la lista `chunks`. Los errores de
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
        >>> asyncio.run(main())  # doctest: +SKIP
    """

    # El Example de arriba se marca +SKIP deliberadamente (AUDIT_CODE, sesión
    # 2026-09-03/04): `convert_document()` necesita un documento real parseable
    # por Docling (carga de modelos incluida) para no fallar -- igual que los
    # tests reales de este módulo, marcados `@pytest.mark.slow` y excluidos de
    # la matriz rápida de CI. Convertir esto en un ejemplo runnable exigiría la
    # misma máquina pesada, en cada job de `pytest --doctest-modules`, solo
    # para un docstring.

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._docling_by_mode: dict[tuple[bool, bool, bool, bool], DoclingConverter] | None = None
        self._chunker: HierarchicalChunker | None = None

    async def __aenter__(self) -> Self:
        self._docling_by_mode = {}
        self._chunker = HierarchicalChunker()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._docling_by_mode = None
        self._chunker = None

    def _get_docling(
        self,
        use_ocr: bool,
        use_gpu: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
    ) -> DoclingConverter:
        if self._docling_by_mode is None:
            raise ConversionError("DocumentConverter debe usarse como context manager async ('async with').")

        key = (use_ocr, use_gpu, extract_images, use_picture_description)
        if key not in self._docling_by_mode:
            options = PdfPipelineOptions()
            options.do_ocr = use_ocr
            if use_ocr and use_gpu:
                # RapidOCR (default, via onnxruntime) es CPU-only. EasyOCR soporta
                # aceleracion GPU (torch/cuda) — se activa solo si el llamante lo pide
                # explicitamente; no es un requisito para que el OCR funcione (AUDIT_PLAN rev. 5).
                options.ocr_options = EasyOcrOptions(use_gpu=True)
            if extract_images:
                options.generate_picture_images = True
            if use_picture_description:
                # smolvlm_picture_description (HuggingFaceTB/SmolVLM-256M-Instruct) en vez
                # del preset granite: mismo patron que EasyOCR/RapidOCR, se prioriza el
                # modelo local mas ligero por defecto (AUDIT_PLAN "soporte de formatos
                # docling"). Solo tiene efecto en InputFormat.PDF/IMAGE (StandardPdfPipeline,
                # unicos formatos configurados abajo con estas `options`) — el resto de
                # formatos (SimplePipeline) lo ignora sin fallar, ver `convert_document`.
                options.do_picture_description = True
                options.picture_description_options = smolvlm_picture_description
            # InputFormat.IMAGE tambien usa StandardPdfPipeline (igual que PDF); sin
            # configurarlo aqui, docling aplicaba sus PdfPipelineOptions() por defecto
            # (do_ocr=True) para imagenes sueltas, ignorando el `use_ocr` del llamante.
            # ImageFormatOption (no PdfFormatOption) para IMAGE: comparte pipeline_cls
            # (StandardPdfPipeline) pero su backend por defecto es ImageDocumentBackend,
            # no el de PDF — reutilizar PdfFormatOption ahi esta deprecado en docling.
            self._docling_by_mode[key] = DoclingConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                    InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
                }
            )
        return self._docling_by_mode[key]

    async def convert_document(
        self,
        source_doc: DocumentMetadata,
        output_dir: Path,
        use_ocr: bool = False,
        use_gpu: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
        scan_roots: Sequence[str] = (),
    ) -> ConversionResult:
        """Convierte `source_doc` a Markdown + JSON bajo `output_dir`.

        Args:
            source_doc: Metadata del documento a convertir (ya escaneado y con hash).
            output_dir: Carpeta raiz de salida (`Conversión/`); se replica la
                estructura de directorios original del documento debajo de ella.
            use_ocr: Si `True`, activa OCR en Docling para este documento.
            use_gpu: Si `True` (y `use_ocr=True`), usa un motor OCR acelerado
                por GPU (EasyOCR) en vez del motor CPU por defecto (RapidOCR).
            extract_images: Si `True`, extrae las imagenes embebidas a
                `<carpeta_salida>/img/<stem>/` y el `.md` las referencia con rutas
                relativas (`ImageRefMode.REFERENCED`) en vez del placeholder
                `<!-- image -->` por defecto. Solo tiene efecto real en documentos
                que usan el pipeline PDF/imagen; el resto de formatos no generan
                imagenes extraibles de la misma forma. Por defecto `False`: cambia
                el formato del `.md` de salida respecto al comportamiento previo,
                asi que es opt-in explicito, no automatico.
            use_picture_description: Si `True`, genera una descripcion textual de
                cada imagen (modelo local `smolvlm_picture_description`) incluida
                en el `.json` de salida — pensado para RAG. Solo tiene efecto en
                documentos PDF/imagen (`StandardPdfPipeline`); se acepta sin error
                para el resto de formatos, pero no hace nada (ver
                `ConversionResult.picture_description_applied`). Coste real no
                trivial: descarga del modelo en el primer uso y latencia de
                inferencia por imagen.
            scan_roots: Carpetas raiz que el usuario indico al escanear (p.ej.
                `clean_paths` de `ScanCommand`). Se usan solo para calcular donde
                cuelga `source_doc.full_path` y replicar esa jerarquia relativa
                bajo `output_dir` (ver `resolve_output_paths`) -- nunca la ruta
                absoluta completa del disco de origen. Vacio por defecto: sin
                ninguna raiz conocida, la salida se aplana a `output_dir/<stem>`.

        Returns:
            ConversionResult con las rutas de salida, si tuvo exito, y si el
            documento requiere OCR (para REQ-004).
        """
        start = time.monotonic()
        output_dir = Path(output_dir)
        # _get_docling() valida el uso como context manager; ese error de programacion
        # se propaga (no se atrapa como fallo de conversion de este documento).
        docling_converter = self._get_docling(use_ocr, use_gpu, extract_images, use_picture_description)

        try:
            docling_result = await asyncio.to_thread(docling_converter.convert, source_doc.full_path)
            ocr_required = self._needs_ocr(docling_result)
            # do_picture_description solo se configura para InputFormat.PDF/IMAGE en
            # _get_docling (StandardPdfPipeline) — el resto de formatos usan SimplePipeline,
            # que no tiene ese paso, asi que el flag pedido por el llamante no tuvo efecto.
            picture_description_applied = use_picture_description and docling_result.input.format in (InputFormat.PDF, InputFormat.IMAGE)
            markdown_path, json_path, images_dir = await self._write_outputs(
                source_doc, docling_result, output_dir, ocr_required, extract_images, picture_description_applied, scan_roots
            )
        # Excepcion amplia deliberada: cualquier fallo de conversion o de escritura de
        # salida (incluida la limpieza de img/<stem>/, AUDIT_CODE) se reporta en
        # ConversionResult (success=False), nunca se relanza — un documento bloqueado
        # (fichero en uso, permiso denegado) no debe abortar el resto del batch.
        except Exception as exc:
            # str(exc) puede ser "" (excepciones sin mensaje, p.ej. algunas fallas
            # internas de bs4/lxml al parsear HTML grande/patologico) -- sin el
            # fallback, el documento queda marcado ERROR sin ninguna pista visible
            # para el usuario (bug real, informe ZAP, sesion 2026-09-05).
            # exc_info=True para que el traceback completo quede en el log aunque
            # el mensaje de usuario (`error=`) tenga que recurrir al fallback.
            if isinstance(exc, MemoryError):
                # MemoryError nunca lleva mensaje propio -- se muestra el tamano del
                # documento (correlacion, no causa cierta: tambien puede deberse a
                # presion de memoria del sistema en ese instante) como pista util en
                # vez del fallback generico (bug real: informe ZAP de ~60 MB, sesion
                # 2026-09-05).
                size_mb = source_doc.size_bytes / 1_048_576
                error_message = f"Memoria insuficiente durante la conversion (documento de {size_mb:.1f} MB)"
            else:
                error_message = str(exc) or f"{type(exc).__name__} sin mensaje de error"
            self.logger.warning(f"Error convirtiendo '{source_doc.full_path}': {error_message}", exc_info=True)
            return ConversionResult(
                source_path=source_doc.full_path,
                markdown_path=None,
                json_path=None,
                success=False,
                error=error_message,
                ocr_required=False,
                duration_seconds=time.monotonic() - start,
                images_dir=None,
                picture_description_applied=False,
            )

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
            images_dir=str(images_dir) if images_dir else None,
            picture_description_applied=picture_description_applied,
        )

    @staticmethod
    def resolve_output_paths(full_path: str, output_dir: Path, scan_roots: Sequence[str] = ()) -> tuple[Path, Path]:
        """Deriva `(markdown_path, json_path)` para el fichero fuente `full_path` bajo `output_dir`.

        Determinista y basado solo en la ruta del fichero fuente (nunca en su
        hash). Si `full_path` cuelga de alguna de `scan_roots` (las carpetas que
        el usuario indico al escanear), replica la jerarquia relativa a esa raiz
        bajo `output_dir` -- nunca la ruta absoluta completa del disco de origen:
        `output_dir` puede vivir en otra rama del arbol de ficheros (p.ej. una
        carpeta de exportacion ajena a lo escaneado), y mezclar ahi la ruta
        absoluta de origen entera generaba una jerarquia duplicada e inexistente
        en vez de una salida valida (bug real: documento .docx con imagenes,
        `[Errno 2] No such file or directory`, sesion 2026-09-05). Si ninguna
        raiz coincide (o no se indica ninguna), usa solo el `stem` del fichero
        -- una unica carpeta plana bajo `output_dir` -- en vez de reconstruir su
        ruta absoluta. Extraido de `_write_outputs` para que el llamante (p.ej.
        `ScanCommand`, al forzar un rescan) pueda localizar la salida de un
        documento sin tener que reconvertirlo.

        Cada segmento (carpetas intermedias y `stem` final) se sanea con
        `rstrip(" .")`: Windows normaliza (quita) espacios/puntos finales de un
        componente SOLO cuando es el ultimo de la ruta que se le pasa a una
        llamada de API -- al crear `img/<stem>/` (donde `stem` SI es el ultimo
        componente) el espacio final desaparecia del directorio real en disco,
        pero al escribir luego un fichero dentro (`img/<stem>/imagen.png`,
        donde `stem` pasa a ser un componente intermedio) no se normalizaba y
        Windows buscaba un directorio con el espacio que nunca existio
        (`[Errno 2] No such file or directory`, bug real: `.docx` con nombre
        terminado en espacio, sesion 2026-09-05).
        """
        resolved = Path(full_path).resolve()
        relative_parts: tuple[str, ...] = ()
        best_root_depth = -1
        for root in scan_roots:
            resolved_root = Path(root).resolve()
            try:
                relative = resolved.relative_to(resolved_root)
            except ValueError:
                continue
            if len(resolved_root.parts) > best_root_depth:
                best_root_depth = len(resolved_root.parts)
                relative_parts = relative.parts
        stem = Path(relative_parts[-1]).stem if relative_parts else resolved.stem
        stem = stem.rstrip(" .")
        dir_parts = [part.rstrip(" .") for part in relative_parts[:-1]]
        target_dir = output_dir.joinpath(*dir_parts) if dir_parts else output_dir
        return target_dir / f"{stem}.md", target_dir / f"{stem}.json"

    @staticmethod
    def resolve_images_dir(markdown_path: Path) -> Path:
        """Carpeta de imagenes namespaced (`img/<stem>/`) junto a `markdown_path` —
        misma convencion que usa `_write_outputs` con `extract_images=True`. Expuesta
        (no privada) para que `ScanCommand._delete_orphaned_outputs` pueda borrarla al
        limpiar la salida de un documento huerfano, sin duplicar la convencion de
        nombrado (AUDIT_CODE)."""
        return markdown_path.parent / "img" / markdown_path.stem

    async def _write_outputs(
        self,
        source_doc: DocumentMetadata,
        # Any: objeto real de Docling (ConversionResult) -- `docling.*` tiene
        # `follow_imports = "skip"` en mypy (pyproject.toml) por incompatibilidad
        # de sus stubs (via scipy-stubs) con Python 3.11 (AUDIT_CODE, sesión
        # 2026-09-03/04).
        docling_result: Any,
        output_dir: Path,
        ocr_required: bool,
        extract_images: bool,
        picture_description_applied: bool,
        scan_roots: Sequence[str] = (),
    ) -> tuple[Path, Path, Path | None]:
        markdown_path, json_path = self.resolve_output_paths(source_doc.full_path, output_dir, scan_roots)
        await asyncio.to_thread(markdown_path.parent.mkdir, parents=True, exist_ok=True)

        images_dir: Path | None = None
        if extract_images:
            # Relativo (no absoluto): `DoclingDocument._get_output_paths` resuelve un
            # artifacts_dir relativo contra `markdown_path.parent` y genera referencias
            # relativas en el .md ("img/<stem>/imagen.png"); uno absoluto produciria
            # rutas absolutas no portables. Se namespacea por `stem` (no una carpeta
            # "img" compartida a secas) para que dos documentos distintos convertidos en
            # el mismo `output_dir` no se pisen las imagenes entre si.
            relative_images_dir = Path("img") / markdown_path.stem
            absolute_images_dir = self.resolve_images_dir(markdown_path)
            # Se borra ANTES de escribir (AUDIT_CODE): `save_as_markdown` solo hace
            # `mkdir(exist_ok=True)`, nunca limpia el directorio previo, y Docling nombra
            # cada imagen con un sufijo de hash de contenido — una reconversion con
            # imagenes distintas (documento editado, o el segundo pase de OCR
            # reconvirtiendo tras el primero) ACUMULARIA ficheros obsoletos en vez de
            # sobrescribirlos, y `_finalize_images_dir` no podria distinguir "sin
            # imagenes en esta conversion" de "restos de una conversion anterior".
            # Sin ignore_errors=True: un fallo real (permiso denegado, fichero
            # bloqueado) debe propagarse y marcar la conversion como fallida (capturado
            # por el try/except de `convert_document`), no dejar `img/<stem>/` a medio
            # limpiar en silencio.
            if await asyncio.to_thread(absolute_images_dir.exists):
                await asyncio.to_thread(shutil.rmtree, absolute_images_dir)
            await asyncio.to_thread(
                docling_result.document.save_as_markdown,
                markdown_path,
                artifacts_dir=relative_images_dir,
                image_mode=ImageRefMode.REFERENCED,
            )
            images_dir = await asyncio.to_thread(self._finalize_images_dir, absolute_images_dir)
        else:
            markdown_text = docling_result.document.export_to_markdown()
            await asyncio.to_thread(markdown_path.write_text, markdown_text, encoding="utf-8")

        document_json = {
            "source_path": source_doc.full_path,
            "title": markdown_path.stem,
            "size_bytes": source_doc.size_bytes,
            "sha256_hash": source_doc.sha256_hash,
            "modified_time": source_doc.modified_time,
            "ocr_required": ocr_required,
            "chunks": await asyncio.to_thread(self._build_chunks, docling_result.document, picture_description_applied),
        }

        await asyncio.to_thread(json_path.write_text, json.dumps(document_json, indent=2, ensure_ascii=False), encoding="utf-8")
        return markdown_path, json_path, images_dir

    @staticmethod
    def _finalize_images_dir(candidate_dir: Path) -> Path | None:
        """Devuelve `candidate_dir` si `save_as_markdown` escribio alguna imagen ahi,
        o `None` tras borrarla si quedo vacia (documento sin imagenes embebidas pese
        a `extract_images=True` — `save_as_markdown` crea el directorio igualmente)."""
        if not candidate_dir.is_dir():
            return None
        if any(candidate_dir.iterdir()):
            return candidate_dir
        candidate_dir.rmdir()
        return None

    # `document: Any` -- objeto real de Docling (DoclingDocument), mismo motivo
    # que `docling_result: Any` en `_write_outputs` (`follow_imports = "skip"`
    # para `docling.*`).
    def _build_chunks(self, document: Any, include_picture_descriptions: bool = False) -> list[dict[str, Any]]:
        """Trocea `document` en chunks por seccion, sin geometria (REQ-003).

        Usa `HierarchicalChunker` en vez de `HybridChunker`: no necesita un
        tokenizer (ni su descarga inicial de HuggingFace), suficiente para
        chunks alineados con la estructura del documento sin acotar por
        limite de tokens (ver AUDIT_PLAN, sesion JSON-para-IA).
        """
        if self._chunker is None:
            raise ConversionError("DocumentConverter debe usarse como context manager async ('async with').")

        chunks = []
        for base_chunk in self._chunker.chunk(document):
            # HierarchicalChunker siempre produce DocChunk (meta: DocMeta); el tipo
            # declarado del iterador es la base generica BaseChunk (meta: BaseMeta).
            chunk = cast(DocChunk, base_chunk)
            page_numbers = sorted({prov.page_no for item in chunk.meta.doc_items for prov in item.prov})
            entry: dict[str, Any] = {
                "text": chunk.text,
                "headings": chunk.meta.headings or [],
                "page_numbers": page_numbers,
            }
            if chunk.meta.captions:
                entry["captions"] = chunk.meta.captions
            if include_picture_descriptions:
                descriptions = self._collect_picture_descriptions(chunk.meta.doc_items)
                if descriptions:
                    entry["image_descriptions"] = descriptions
            chunks.append(entry)
        return chunks

    @staticmethod
    def _collect_picture_descriptions(doc_items: list[DocItem]) -> list[str]:
        """Extrae el texto de `PictureDescriptionData` de las `PictureItem` de
        `doc_items` (generadas por `do_picture_description`, ver `_get_docling`)."""
        descriptions = []
        for item in doc_items:
            if not isinstance(item, PictureItem):
                continue
            for annotation in item.annotations:
                if isinstance(annotation, PictureDescriptionData):
                    descriptions.append(annotation.text)
        return descriptions

    # `docling_result: Any` -- mismo motivo que en `_write_outputs`/`_build_chunks`
    # (objeto real de Docling, `follow_imports = "skip"` para `docling.*`).
    @staticmethod
    def _needs_ocr(docling_result: Any) -> bool:
        """`True` si el documento no tiene capa de texto nativa (`parse_score`
        es `NaN`) — señal confirmada empiricamente en el spike de REQ-004."""
        parse_score = docling_result.confidence.parse_score
        return math.isnan(parse_score)


__all__ = ["DocumentConverter"]
