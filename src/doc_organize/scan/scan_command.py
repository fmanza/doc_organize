"""
Orquestación de escaneo + caché + conversión, y deduplicación bajo demanda.

Extraído de `main.py` en Fase D-2b (§2.7.3): `ScanCommand` es un módulo de
orquestación Level 3 (`architecture.instructions.md`) usado por dos entry points
distintos — el CLI (`main.py`, Fase D-1) y la interfaz web (`web/routes/scan.py`,
Fase D-2b) — así que no debe pertenecer a ninguno de los dos; vive en su propio
módulo para que ninguno dependa del otro.

`run`/`run_streaming` (escanear+cachear+convertir) y `deduplicate` (buscar y
mover duplicados) son dos acciones independientes, no un único pipeline: la
deduplicación es una acción explícita a petición del usuario, no un paso
automático del escaneo — ambos entry points la ofrecen como una operación
separada que el usuario ejecuta antes de escanear.
"""

import asyncio
import json
import shutil
import uuid

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter, OCRScheduler
from doc_organize.core.constants import MAX_AUTO_ERROR_RETRIES
from doc_organize.core.models import (
    CacheEntry,
    ConversionResult,
    ConversionStatus,
    DocumentMetadata,
    DocumentStatus,
    ScanErrorEntry,
    ScanErrorReport,
    ScanEvent,
    ScanEventType,
)
from doc_organize.dedup import DeduplicationManager
from doc_organize.scanner import DocumentScanner
from doc_organize.utils.logging import get_logger
from doc_organize.validators import FolderValidator

logger = get_logger(__name__)


@dataclass
class ScanSummary:
    """Resumen imprimible del resultado de `scan` (uso interno, no un modelo de dominio)."""

    scanned: int = 0
    new: int = 0
    modified: int = 0
    unchanged: int = 0
    converted: int = 0
    conversion_errors: int = 0
    ocr_required: int = 0
    ocr_processed: int = 0
    error_retries: int = 0
    error_retries_capped: int = 0

    def render(self) -> str:
        lines = [
            f"Documentos escaneados: {self.scanned}",
            f"  nuevos: {self.new} | modificados: {self.modified} | sin cambios: {self.unchanged}",
            f"Convertidos: {self.converted} (errores: {self.conversion_errors}, reintentos de errores previos: {self.error_retries})",
            f"Requieren OCR: {self.ocr_required} (procesados con OCR: {self.ocr_processed})",
        ]
        if self.error_retries_capped:
            lines.append(f"Sin reintentar (límite de {MAX_AUTO_ERROR_RETRIES} reintentos alcanzado): {self.error_retries_capped}")
        return "\n".join(lines)


@dataclass
class DeduplicationSummary:
    """Resumen imprimible del resultado de `ScanCommand.deduplicate()` (uso interno,
    no un modelo de dominio — el contrato JSON de la web usa su propio Pydantic
    response model, ver `web/routes/scan.py`)."""

    groups_found: int = 0
    moved: int = 0
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Grupos de duplicados detectados: {self.groups_found}",
            f"Archivos movidos a duplicados/: {self.moved}",
        ]
        if self.warnings:
            lines.append(f"Avisos ({len(self.warnings)}):")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        return "\n".join(lines)


class ScanCommand:
    """Orquesta escaneo + caché + conversión, y deduplicación bajo demanda (Fase D-1, Fase D-2b).

    No es un módulo de dominio nuevo (`workflow/` sigue fuera de alcance, v0.2.0):
    es una capa de pegamento — Level 3 según `architecture.instructions.md` — que
    solo llama a los servicios ya implementados de Level 2 con las rutas resueltas
    por `ProjectRegistry` o por flags explícitos, sin cambiar ninguno de sus
    contratos. Compartida por el CLI (`main.py`) y la web (`web/routes/scan.py`).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    async def run(
        self,
        paths: list[str],
        output_dir: Path,
        cache_db: Path,
        folders_json: Path,
        use_ocr: bool,
        use_gpu: bool,
        force: bool = False,
        include_audio_video: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
        error_log_path: Path | None = None,
    ) -> ScanSummary:
        """Ejecuta el pipeline y devuelve solo el resumen final (contrato sin cambios,
        Fase D-1). Consume `run_streaming()` y se queda con su evento `completed` —
        ver `§2.7.3` (Fase D-2b): la orquestación real vive ahora ahí.
        """
        summary = ScanSummary()
        async for event in self.run_streaming(
            paths,
            output_dir,
            cache_db,
            folders_json,
            use_ocr,
            use_gpu,
            force,
            include_audio_video,
            extract_images,
            use_picture_description,
            error_log_path,
        ):
            if event.event is ScanEventType.COMPLETED:
                summary = ScanSummary(**event.data)
        return summary

    async def run_streaming(
        self,
        paths: list[str],
        output_dir: Path,
        cache_db: Path,
        folders_json: Path,
        use_ocr: bool,
        use_gpu: bool,
        force: bool = False,
        include_audio_video: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
        error_log_path: Path | None = None,
    ) -> AsyncIterator[ScanEvent]:
        """Orquesta escaneo + caché + conversión, emitiendo progreso.

        Fase D-2b (`§2.7.3`): misma orquestación que antes vivía solo en `run()`,
        ahora factorizada aquí para que `web/routes/scan.py` pueda retransmitir cada
        evento por WebSocket sin duplicar la lógica del pipeline. Cada fase delega en
        un método privado (reduce la complejidad ciclomática de este método a la de
        "qué fases hay y en qué orden", no al detalle de cada una).

        La deduplicación NO forma parte de este pipeline: es una acción separada y
        explícita a petición del usuario (`deduplicate()`, más abajo) — la página
        "Escanear" bloquea este paso hasta que esa otra se haya ejecutado en la
        misma visita. Antes de esta sesión, `run_streaming()` deduplicaba
        internamente (opcional primero, incondicional después); se separó porque
        un pipeline combinado no permite exigir "deduplicar antes de escanear"
        como dos pasos distintos que el usuario controla.

        Args:
            force: Si `True`, ignora la caché existente (se vacía antes de
                comparar, así que `get_changes()` trata todos los documentos
                como nuevos) y borra los `.md`/`.json` ya generados de
                ficheros que estaban en la caché anterior pero ya no aparecen
                en este escaneo (renombrados, movidos o eliminados desde la
                última pasada). Los ficheros que sí siguen presentes no se
                borran de antemano: `DocumentConverter` ya sobrescribe su
                salida al reconvertirlos, en el mismo path derivado de su ruta.
            error_log_path: Si se indica y esta ejecución produce algún error de
                conversión/OCR, se añade una línea `ScanErrorReport` a este fichero
                JSONL (append-only, se crea la carpeta si falta). `None` (por
                defecto) desactiva la persistencia del histórico de errores sin
                afectar al resto del pipeline — usado por llamadores que no operan
                sobre un proyecto (p. ej. el CLI sin `--project`).
        """
        summary = ScanSummary()
        yield ScanEvent(event=ScanEventType.STARTED, data={})

        clean_paths, path_warnings = await self._resolve_scan_paths(paths, folders_json)

        async with DocumentScanner() as scanner:
            # exclude_dir=output_dir: sin esto, si una de `clean_paths` contiene el
            # `output_dir` de un escaneo previo con `extract_images=True`, el escaneo
            # redescubre las imagenes ya extraidas (`img/<stem>/*.png`) como
            # documentos nuevos; una reconversion posterior en el mismo pase borra esa
            # carpeta (`shutil.rmtree` en `DocumentConverter._write_outputs`) y la
            # "conversion" de esa imagen falla con FileNotFoundError.
            scan_result = await scanner.scan_folders(
                clean_paths, include_audio_video=include_audio_video, exclude_dir=output_dir.resolve()
            )
        summary.scanned = len(scan_result.documents)

        async with CacheManager(cache_db) as cache:
            cached_entries = await cache.load_cache()
            if force:
                current_paths = {doc.full_path for doc in scan_result.documents}
                orphaned_paths = set(cached_entries) - current_paths
                await self._delete_orphaned_outputs(orphaned_paths, output_dir)
                await cache.clear()
                cached_entries = {}
            new_files, modified_files, unchanged_files = cache.get_changes(cached_entries, scan_result.documents)
            summary.new, summary.modified, summary.unchanged = (
                len(new_files),
                len(modified_files),
                len(unchanged_files),
            )
            new_set = set(new_files)
            modified_set = set(modified_files)
            to_process_paths = new_set | modified_set
            docs_by_path = {doc.full_path: doc for doc in scan_result.documents}
            error_retry_paths, error_retries_capped_paths = self._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths)
            summary.error_retries = len(error_retry_paths)
            summary.error_retries_capped = len(error_retries_capped_paths)
            already_converting = to_process_paths | error_retry_paths
            docs_to_process = [docs_by_path[path] for path in already_converting if path in docs_by_path]
            yield ScanEvent(
                event=ScanEventType.SCANNED,
                data={
                    "scanned": summary.scanned,
                    "new": summary.new,
                    "modified": summary.modified,
                    "unchanged": summary.unchanged,
                    # Antes (checkboxes + preflight `/folders/validate`) el cliente
                    # ya llegaba aquí con rutas limpias y el usuario veía cualquier
                    # aviso antes de escanear. Ahora las rutas vienen siempre de
                    # `ScannedFoldersStore` sin ese preflight, así que una carpeta
                    # guardada que ya no exista en disco se descarta en silencio si
                    # no se retransmite aquí — el cliente ya muestra cada evento tal
                    # cual en el cuadro de progreso.
                    "warnings": path_warnings,
                },
            )

            entries: list[CacheEntry] = []
            ocr_candidates: list[DocumentMetadata] = []

            async for event in self._convert_documents(
                docs_to_process,
                output_dir,
                new_set,
                modified_set,
                cached_entries,
                summary,
                entries,
                ocr_candidates,
                extract_images,
                use_picture_description,
            ):
                yield event

            if use_ocr:
                self._collect_stale_ocr_candidates(cached_entries, docs_by_path, already_converting, ocr_candidates)
                async for event in self._process_ocr(
                    ocr_candidates, output_dir, use_gpu, entries, cached_entries, summary, extract_images, use_picture_description
                ):
                    yield event

            await cache.save_entries(entries)

            if error_log_path is not None:
                error_entries = self._collect_error_entries(entries, error_retries_capped_paths, cached_entries)
                if error_entries:
                    report = ScanErrorReport(
                        scan_run_id=uuid.uuid4().hex,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        total_scanned=summary.scanned,
                        entries=error_entries,
                    )
                    await self._persist_error_report(error_log_path, report)

        yield ScanEvent(event=ScanEventType.COMPLETED, data=asdict(summary))

    async def _resolve_scan_paths(self, paths: list[str], folders_json: Path) -> tuple[list[str], list[str]]:
        """Valida `paths`, persiste el resultado en `folders_json`, devuelve
        `(rutas limpias, avisos de validación)`.

        `folders_json` es releído más tarde por `web/routes/duplicates.py` (Fase D-2c,
        `§2.7.4`) para re-escanear el proyecto sin que el usuario tenga que volver a
        indicar las carpetas.
        """
        validation = FolderValidator().validate_folder_set(paths)
        for warning in validation.warnings:
            self.logger.warning(warning)
        await asyncio.to_thread(folders_json.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            folders_json.write_text,
            json.dumps({"paths": validation.clean_paths}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return validation.clean_paths, validation.warnings

    @staticmethod
    async def _delete_orphaned_outputs(orphaned_paths: set[str], output_dir: Path) -> None:
        """Borra el `.md`/`.json`/`img/<stem>/` de `orphaned_paths` bajo `output_dir`, si existen.

        Usado por "forzar rescan" (`force=True`): `orphaned_paths` son rutas que
        estaban en la caché anterior pero no en el escaneo actual (fichero
        renombrado, movido o eliminado desde la última pasada) — su salida
        antigua, calculada con el mismo algoritmo que `DocumentConverter` usa al
        generarla, quedaría huérfana si no se borra aquí. Incluye `img/<stem>/`
        (AUDIT_CODE): sin esto, la carpeta de imágenes de un documento borrado con
        `extract_images=True` quedaba huérfana para siempre.
        """
        for path in orphaned_paths:
            markdown_path, json_path = DocumentConverter.resolve_output_paths(path, output_dir)
            for artifact in (markdown_path, json_path):
                if await asyncio.to_thread(artifact.exists):
                    await asyncio.to_thread(artifact.unlink)
            images_dir = DocumentConverter.resolve_images_dir(markdown_path)
            # Sin ignore_errors=True (AUDIT_CODE): un fallo real (permiso denegado,
            # fichero bloqueado) debe quedar registrado, no silenciado — coherente con
            # que el `.unlink()` de arriba tampoco traga errores. `images_dir` puede no
            # existir (documento nunca convertido con extract_images=True); eso es
            # normal y no se loguea como fallo.
            if await asyncio.to_thread(images_dir.exists):
                try:
                    await asyncio.to_thread(shutil.rmtree, images_dir)
                except OSError as exc:
                    logger.warning(f"No se pudo borrar '{images_dir}' (huérfana): {exc}")

    async def deduplicate(self, paths: list[str], duplicates_dir: Path, folders_json: Path) -> DeduplicationSummary:
        """Busca y mueve duplicados en `paths`, a petición explícita del usuario.

        Acción independiente del pipeline de `run`/`run_streaming` (ver su
        docstring): no convierte ni cachea nada, solo escanea para poder
        calcular hashes, detecta duplicados y los mueve. Reutiliza
        `_resolve_scan_paths()` para que `folders_json` quede escrito igual que
        tras un escaneo — así `web/routes/duplicates.py` funciona aunque el
        usuario solo haya deduplicado y no haya llegado a escanear todavía.

        Llama a `resolve_duplicates()` siempre, incluso sin grupos (`groups`
        vacío): así cada ejecución de "Buscar duplicados" queda registrada en
        `DEDUP_HISTORY.jsonl` (histórico completo de cada vez que se pulsó el
        botón, no solo de las veces que se movió algo).
        """
        clean_paths, warnings = await self._resolve_scan_paths(paths, folders_json)

        async with DocumentScanner() as scanner:
            scan_result = await scanner.scan_folders(clean_paths)

        dedup_manager = DeduplicationManager()
        groups = dedup_manager.find_duplicates(scan_result.documents)
        report = await dedup_manager.resolve_duplicates(groups, duplicates_dir)
        moved = report.total_exact_duplicates + report.total_version_conflicts

        return DeduplicationSummary(groups_found=len(groups), moved=moved, warnings=warnings)

    async def _convert_documents(
        self,
        docs_to_process: list[DocumentMetadata],
        output_dir: Path,
        new_set: set[str],
        modified_set: set[str],
        cached_entries: dict[str, CacheEntry],
        summary: ScanSummary,
        entries: list[CacheEntry],
        ocr_candidates: list[DocumentMetadata],
        extract_images: bool = False,
        use_picture_description: bool = False,
    ) -> AsyncIterator[ScanEvent]:
        """Convierte cada documento, yieldeando un `FILE_CONVERTED` por unidad.

        `docs_to_process` incluye tanto ficheros nuevos/modificados (`new_set`/
        `modified_set`) como reintentos de ficheros sin cambios cuya conversión
        anterior quedó en `ERROR` (`_collect_stale_error_paths`) — estos últimos
        conservan `status=UNCHANGED`, ya que su hash no varió. `cached_entries`
        se usa solo para leer el `error_retry_count` previo de cada documento
        (`_build_entry` lo incrementa en fallo / lo resetea en éxito).

        Muta `summary`/`entries`/`ocr_candidates` in-place (son del llamador) en vez
        de devolverlos: es la forma más simple de combinar "acumula resultados" con
        "yieldea progreso" sin duplicar la lógica en dos métodos (uno con `yield`,
        otro con `return`) — contrato interno de esta clase, no una API pública.
        """
        async with DocumentConverter() as converter:
            for doc in docs_to_process:
                result = await converter.convert_document(
                    doc, output_dir, use_ocr=False, extract_images=extract_images, use_picture_description=use_picture_description
                )
                if doc.full_path in new_set:
                    status = DocumentStatus.NEW
                elif doc.full_path in modified_set:
                    status = DocumentStatus.MODIFIED
                else:
                    status = DocumentStatus.UNCHANGED
                if result.success:
                    summary.converted += 1
                else:
                    summary.conversion_errors += 1
                if result.ocr_required:
                    summary.ocr_required += 1
                    ocr_candidates.append(doc)
                cached = cached_entries.get(doc.full_path)
                previous_retry_count = cached.error_retry_count if cached else 0
                entries.append(self._build_entry(doc, result, status, ocr_pending=result.ocr_required, previous_retry_count=previous_retry_count))
                yield ScanEvent(
                    event=ScanEventType.FILE_CONVERTED,
                    data={"path": doc.full_path, "success": result.success, "ocr_required": result.ocr_required},
                )

    @staticmethod
    def _collect_stale_error_paths(
        cached_entries: dict[str, CacheEntry],
        docs_by_path: dict[str, DocumentMetadata],
        to_process_paths: set[str],
    ) -> tuple[set[str], set[str]]:
        """Devuelve `(reintentables, límite_agotado)`: rutas de documentos sin
        cambios cuya conversión anterior quedó en `ERROR`, separadas según si ya
        acumulan `MAX_AUTO_ERROR_RETRIES` fallos consecutivos.

        Sin esto, `get_changes()` clasifica estos ficheros como `unchanged` (su
        hash no varió) y quedarían excluidos de `docs_to_process` para siempre,
        obligando a "forzar rescan completo" (que reprocesa todo el proyecto)
        para poder reintentar un único fichero fallido. El límite evita que un
        fichero irrecuperable (p.ej. cifrado) se reprocese en cada escaneo para
        siempre; las rutas con límite agotado se devuelven igualmente (no se
        descartan sin más) para que el llamante las refleje en
        `ScanSummary.error_retries_capped` — el límite no debe volver a excluir
        ficheros del resumen en silencio, que es justo el bug que este método
        resuelve para el caso general.
        """
        retryable: set[str] = set()
        capped: set[str] = set()
        for entry in cached_entries.values():
            if entry.conversion_status != ConversionStatus.ERROR:
                continue
            if entry.file_path in to_process_paths or entry.file_path not in docs_by_path:
                continue
            if entry.error_retry_count >= MAX_AUTO_ERROR_RETRIES:
                capped.add(entry.file_path)
            else:
                retryable.add(entry.file_path)
        return retryable, capped

    @staticmethod
    def _collect_stale_ocr_candidates(
        cached_entries: dict[str, CacheEntry],
        docs_by_path: dict[str, DocumentMetadata],
        to_process_paths: set[str],
        ocr_candidates: list[DocumentMetadata],
    ) -> None:
        """Añade (in-place) documentos sin cambios que quedaron `OCR_PENDING` en una
        ejecución anterior, para que `--use-ocr` los recoja aunque no se hayan vuelto
        a escanear como nuevos/modificados en esta pasada."""
        already_candidate_paths = {doc.full_path for doc in ocr_candidates}
        for entry in cached_entries.values():
            if (
                entry.conversion_status == ConversionStatus.OCR_PENDING
                and entry.file_path not in to_process_paths
                and entry.file_path not in already_candidate_paths
                and entry.file_path in docs_by_path
            ):
                ocr_candidates.append(docs_by_path[entry.file_path])

    async def _process_ocr(
        self,
        ocr_candidates: list[DocumentMetadata],
        output_dir: Path,
        use_gpu: bool,
        entries: list[CacheEntry],
        cached_entries: dict[str, CacheEntry],
        summary: ScanSummary,
        extract_images: bool = False,
        use_picture_description: bool = False,
    ) -> AsyncIterator[ScanEvent]:
        """Reprocesa `ocr_candidates` con OCR, yieldeando un `OCR_PROCESSED` por unidad.

        `extract_images`/`use_picture_description` se propagan igual que en la primera
        pasada (`_convert_documents`): un documento que necesitó OCR no debe perder
        estas opciones solo por resolverse en esta segunda pasada.

        Muta `entries`/`summary` in-place, mismo contrato que `_convert_documents`. Un
        `return` temprano en una función `async def` con `yield` es válido: simplemente
        termina el generador sin producir nada, no hace falta un generador vacío aparte.
        """
        if not ocr_candidates:
            return
        ocr_results = await OCRScheduler().process_with_ocr(
            ocr_candidates, output_dir, use_gpu=use_gpu, extract_images=extract_images, use_picture_description=use_picture_description
        )
        summary.ocr_processed = sum(1 for result in ocr_results if result.success)
        entries_by_path = {entry.file_path: entry for entry in entries}
        for doc, result in zip(ocr_candidates, ocr_results, strict=True):
            previous = entries_by_path.get(doc.full_path)
            status = previous.status if previous else DocumentStatus.UNCHANGED
            if previous is not None:
                previous_retry_count = previous.error_retry_count
            else:
                cached = cached_entries.get(doc.full_path)
                previous_retry_count = cached.error_retry_count if cached else 0
            new_entry = self._build_entry(doc, result, status, ocr_pending=False, previous_retry_count=previous_retry_count)
            entries_by_path[doc.full_path] = new_entry
            yield ScanEvent(event=ScanEventType.OCR_PROCESSED, data={"path": doc.full_path, "success": result.success})
        entries[:] = list(entries_by_path.values())

    @staticmethod
    def _build_entry(
        doc: DocumentMetadata,
        result: ConversionResult,
        status: DocumentStatus,
        *,
        ocr_pending: bool,
        previous_retry_count: int = 0,
    ) -> CacheEntry:
        if not result.success:
            conversion_status = ConversionStatus.ERROR
            error_retry_count = previous_retry_count + 1
        else:
            error_retry_count = 0
            conversion_status = ConversionStatus.OCR_PENDING if ocr_pending else ConversionStatus.SUCCESS
        return CacheEntry(
            file_path=doc.full_path,
            sha256_hash=doc.sha256_hash,
            timestamp=doc.modified_time,
            status=status,
            conversion_status=conversion_status,
            error_message=result.error,
            error_retry_count=error_retry_count,
        )

    @staticmethod
    def _collect_error_entries(
        entries: list[CacheEntry],
        capped_paths: set[str],
        cached_entries: dict[str, CacheEntry],
    ) -> list[ScanErrorEntry]:
        """Construye los `ScanErrorEntry` de esta ejecución: ficheros reprocesados que
        siguen en `ERROR` (`entries`) más los que agotaron `MAX_AUTO_ERROR_RETRIES` y
        no se reintentaron en esta pasada (`capped_paths`) — su `error_message`/
        `error_retry_count` se leen de la caché anterior (`cached_entries`), ya que
        `_collect_stale_error_paths` los excluye deliberadamente de `entries`.

        Ordena el resultado por `file_path` (AUDIT_CODE): `entries` recorre
        `docs_to_process`, cuyo orden depende de la iteración de un `set`
        (`already_converting`, en `run_streaming`) — sin este orden explícito, el
        orden de los ficheros dentro de un mismo `ScanErrorReport` persistido sería
        no determinista entre ejecuciones idénticas.
        """
        error_entries = [
            ScanErrorEntry(
                file_path=entry.file_path,
                error_message=entry.error_message or "",
                error_retry_count=entry.error_retry_count,
                capped=False,
            )
            for entry in entries
            if entry.conversion_status == ConversionStatus.ERROR
        ]
        for path in capped_paths:
            cached = cached_entries.get(path)
            if cached is not None:
                error_entries.append(
                    ScanErrorEntry(
                        file_path=path,
                        error_message=cached.error_message or "",
                        error_retry_count=cached.error_retry_count,
                        capped=True,
                    )
                )
        return sorted(error_entries, key=lambda entry: entry.file_path)

    @staticmethod
    async def _persist_error_report(error_log_path: Path, report: ScanErrorReport) -> None:
        """Añade `report` como una línea JSON a `error_log_path` (crea la carpeta
        contenedora si falta). Mismo patrón append-only que `DEDUP_HISTORY.jsonl`
        (`web/routes/duplicates.py`): una línea por ejecución, nunca se reescribe."""
        await asyncio.to_thread(error_log_path.parent.mkdir, parents=True, exist_ok=True)

        def _append() -> None:
            with error_log_path.open("a", encoding="utf-8") as handle:
                handle.write(report.model_dump_json() + "\n")

        await asyncio.to_thread(_append)


__all__ = ["DeduplicationSummary", "ScanCommand", "ScanSummary"]
