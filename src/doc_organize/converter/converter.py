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
from typing import Any, Literal, Self, cast

from docling.datamodel.base_models import FormatToExtensions, InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions, smolvlm_picture_description
from docling.datamodel.settings import settings as docling_settings
from docling.document_converter import DocumentConverter as DoclingConverter, ImageFormatOption, PdfFormatOption
from docling_core.transforms.chunker.doc_chunk import DocChunk
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.items.node import DocItem
from docling_core.types.doc.items.picture.picture import PictureDescriptionData, PictureItem

from doc_organize.core.exceptions import ConversionError, ModelsNotAvailableError
from doc_organize.core.models import ConversionResult, DocumentMetadata
from doc_organize.projects.layout import relative_source_path, resolve_images_dir, resolve_output_paths
from doc_organize.utils.logging import get_logger
from doc_organize.utils.office_detector import detect_office_status

#: Extensiones que Docling convierte con el pipeline PDF/imagen, el único que usa modelos (layout, tablas, OCR).
_MODEL_PIPELINE_EXTENSIONS = frozenset(FormatToExtensions[InputFormat.PDF] + FormatToExtensions[InputFormat.IMAGE])


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

    Los modelos de Docling (layout, tablas, OCR) se descargan la primera vez que se usan, salvo que se indique
    `artifacts_path` (carpeta con los modelos ya descargados, p. ej. con `docling-tools models download`): entonces
    Docling solo los lee de ahí. Con `allow_model_downloads=False` esa carpeta es obligatoria (la indicada o
    `DOCLING_ARTIFACTS_PATH`) y, si falta un modelo, `convert_document` lanza `ModelsNotAvailableError` en vez de
    marcar cada documento como fallido (L-10b, G17).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
        artifacts_path (Path | None): Carpeta de modelos de Docling, si se indicó.
        allow_model_downloads (bool): Si Docling puede descargar los modelos que falten.

    Example:
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def main():
        ...     async with DocumentConverter(artifacts_path=Path("/modelos"), allow_model_downloads=False) as converter:
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

    def __init__(self, *, artifacts_path: Path | str | None = None, allow_model_downloads: bool = True) -> None:
        self.logger = get_logger(__name__)
        self.artifacts_path = Path(artifacts_path).expanduser() if artifacts_path is not None else None
        self.allow_model_downloads = allow_model_downloads
        self._docling_by_mode: dict[tuple[bool, bool, bool, bool], DoclingConverter] | None = None
        self._initialized_modes: set[tuple[bool, bool, bool, bool]] = set()
        self._chunker: HierarchicalChunker | None = None

    async def __aenter__(self) -> Self:
        self._docling_by_mode = {}
        self._chunker = HierarchicalChunker()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._docling_by_mode = None
        self._initialized_modes = set()
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
            if self.artifacts_path is not None:
                options.artifacts_path = self.artifacts_path
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

    async def _ensure_models(self, docling_converter: DoclingConverter, key: tuple[bool, bool, bool, bool], extension: str) -> None:
        """Con descargas prohibidas, carga los modelos del pipeline PDF/imagen antes del primer documento (L-10b).

        Un modelo que falta se detecta aquí, una vez por modo, como `ModelsNotAvailableError` (que se propaga), y no
        como un error repetido en cada documento. El resto de formatos (Word, HTML…) no usa modelos y no se comprueba.
        """
        if self.allow_model_downloads or extension not in _MODEL_PIPELINE_EXTENSIONS or key in self._initialized_modes:
            return
        folder = self.artifacts_path or docling_settings.artifacts_path
        if folder is None:
            raise ModelsNotAvailableError(
                "Las descargas de modelos están prohibidas y no hay carpeta de modelos: indica `artifacts_path` "
                "(o DOCLING_ARTIFACTS_PATH) con los modelos descargados (`docling-tools models download`)."
            )
        try:
            await asyncio.to_thread(docling_converter.initialize_pipeline, InputFormat.PDF)
        except Exception as exc:  # Docling lanza RuntimeError, FileNotFoundError u OSError según el modelo
            raise ModelsNotAvailableError(f"Faltan modelos de Docling en '{folder}' y las descargas están prohibidas: {exc}") from exc
        self._initialized_modes.add(key)

    async def convert_document(
        self,
        source_doc: DocumentMetadata,
        output_dir: Path,
        use_ocr: bool = False,
        use_gpu: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
        scan_roots: Sequence[str] = (),
        *,
        include_root_name: bool = False,
        json_source_path: Literal["relative", "absolute"] = "relative",
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
            include_root_name: Antepone el nombre de la raiz a la ruta de salida
                (ver `resolve_output_paths`, L-10c). Por defecto `False`.
            json_source_path: `source_path` del `.json`: `"relative"` (por defecto
                desde 0.12.0, ruta relativa a la raiz escaneada, sin rutas del
                servidor, G23) o `"absolute"` (la ruta completa, como antes).

        Returns:
            ConversionResult con las rutas de salida, si tuvo exito, y si el
            documento requiere OCR (para REQ-004).

        Raises:
            ModelsNotAvailableError: `allow_model_downloads=False` y faltan modelos
                de Docling (se comprueba con el primer PDF/imagen de cada modo).
        """
        start = time.monotonic()

        # Corte temprano para .xls: Docling delega en LibreOffice (binario
        # externo, no instalado via pip) la conversion a .xlsx antes de poder
        # parsearlo, y sin el en el PATH esa conversion falla siempre (nunca
        # es un problema transitorio del documento). Sin este corte, cada .xls
        # agota los reintentos automaticos con el mismo mensaje generico de
        # Docling (bug real: sesion 2026-09-16).
        if source_doc.extension == "xls":
            office_status = detect_office_status()
            if not office_status.libreoffice_installed:
                self.logger.warning(f"Omitiendo conversion de '{source_doc.full_path}': {office_status.instructions}")
                return ConversionResult(
                    source_path=source_doc.full_path,
                    markdown_path=None,
                    json_path=None,
                    success=False,
                    error=office_status.instructions,
                    ocr_required=False,
                    duration_seconds=time.monotonic() - start,
                    images_dir=None,
                    picture_description_applied=False,
                )

        output_dir = Path(output_dir)
        # _get_docling() valida el uso como context manager; ese error de programacion
        # se propaga (no se atrapa como fallo de conversion de este documento).
        docling_converter = self._get_docling(use_ocr, use_gpu, extract_images, use_picture_description)
        await self._ensure_models(docling_converter, (use_ocr, use_gpu, extract_images, use_picture_description), source_doc.extension)

        try:
            docling_result = await asyncio.to_thread(docling_converter.convert, source_doc.full_path)
            ocr_required = self._needs_ocr(docling_result)
            # do_picture_description solo se configura para InputFormat.PDF/IMAGE en
            # _get_docling (StandardPdfPipeline) — el resto de formatos usan SimplePipeline,
            # que no tiene ese paso, asi que el flag pedido por el llamante no tuvo efecto.
            picture_description_applied = use_picture_description and docling_result.input.format in (InputFormat.PDF, InputFormat.IMAGE)
            markdown_path, json_path, images_dir = await self._write_outputs(
                source_doc,
                docling_result,
                output_dir,
                ocr_required,
                extract_images,
                picture_description_applied,
                scan_roots,
                include_root_name=include_root_name,
                json_source_path=json_source_path,
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
                cause_hint = self._root_cause_hint(exc, error_message)
                if cause_hint:
                    error_message = f"{error_message} (causa: {cause_hint})"
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
    def resolve_output_paths(
        full_path: str, output_dir: Path, scan_roots: Sequence[str] = (), *, include_root_name: bool = False
    ) -> tuple[Path, Path]:
        """Alias de `doc_organize.projects.layout.resolve_output_paths` (movida en 0.12.0 a un módulo sin Docling, G20)."""
        return resolve_output_paths(full_path, output_dir, scan_roots, include_root_name=include_root_name)

    @staticmethod
    def resolve_images_dir(markdown_path: Path) -> Path:
        """Alias de `doc_organize.projects.layout.resolve_images_dir` (movida en 0.12.0, G20)."""
        return resolve_images_dir(markdown_path)

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
        *,
        include_root_name: bool = False,
        json_source_path: Literal["relative", "absolute"] = "relative",
    ) -> tuple[Path, Path, Path | None]:
        markdown_path, json_path = resolve_output_paths(source_doc.full_path, output_dir, scan_roots, include_root_name=include_root_name)
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
            absolute_images_dir = resolve_images_dir(markdown_path)
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
            "source_path": (source_doc.full_path if json_source_path == "absolute" else relative_source_path(source_doc.full_path, scan_roots)),
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

    @staticmethod
    def _root_cause_hint(exc: BaseException, error_message: str) -> str | None:
        """Busca en la cadena `exc.__cause__` (hasta 2 niveles) un mensaje que
        no este ya incluido en `error_message`, para dar una pista mas
        accionable que el envoltorio generico de Docling.

        Docling encadena la excepcion original del backend via `raise ...
        from ...` (ver `document_converter.py`, docling#1920) precisamente
        para que el llamante pueda diagnosticar la causa real -- p.ej. un
        `ConversionError` de `MsExcelDocumentBackend` cuyo primer `__cause__`
        (`DocumentLoadError`) ya esta repetido en `error_message`, pero cuyo
        segundo `__cause__` (`zipfile.BadZipFile: File is not a zip file`)
        revela que el .xlsx fuente esta truncado/corrupto (bug real, sesion
        2026-09-16).
        """
        cause = exc.__cause__
        for _ in range(2):
            if cause is None:
                return None
            cause_text = str(cause).strip()
            if cause_text and cause_text not in error_message:
                return cause_text
            cause = cause.__cause__
        return None


__all__ = ["DocumentConverter"]
