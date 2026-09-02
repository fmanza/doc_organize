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

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from doc_organize.cache import CacheManager
from doc_organize.converter import DocumentConverter, OCRScheduler
from doc_organize.core.models import (
    CacheEntry,
    ConversionResult,
    ConversionStatus,
    DocumentMetadata,
    DocumentStatus,
    ScanEvent,
    ScanEventType,
)
from doc_organize.dedup import DeduplicationManager
from doc_organize.scanner import DocumentScanner
from doc_organize.utils.logging import get_logger
from doc_organize.validators import FolderValidator


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

    def render(self) -> str:
        return "\n".join(
            [
                f"Documentos escaneados: {self.scanned}",
                f"  nuevos: {self.new} | modificados: {self.modified} | sin cambios: {self.unchanged}",
                f"Convertidos: {self.converted} (errores: {self.conversion_errors})",
                f"Requieren OCR: {self.ocr_required} (procesados con OCR: {self.ocr_processed})",
            ]
        )


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
    ) -> ScanSummary:
        """Ejecuta el pipeline y devuelve solo el resumen final (contrato sin cambios,
        Fase D-1). Consume `run_streaming()` y se queda con su evento `completed` —
        ver `§2.7.3` (Fase D-2b): la orquestación real vive ahora ahí.
        """
        summary = ScanSummary()
        async for event in self.run_streaming(paths, output_dir, cache_db, folders_json, use_ocr, use_gpu, force):
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
        """
        summary = ScanSummary()
        yield ScanEvent(event=ScanEventType.STARTED, data={})

        clean_paths, path_warnings = await self._resolve_scan_paths(paths, folders_json)

        async with DocumentScanner() as scanner:
            scan_result = await scanner.scan_folders(clean_paths)
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
            error_retry_paths = self._collect_stale_error_paths(cached_entries, docs_by_path, to_process_paths)
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

            async for event in self._convert_documents(docs_to_process, output_dir, new_set, modified_set, summary, entries, ocr_candidates):
                yield event

            if use_ocr:
                self._collect_stale_ocr_candidates(cached_entries, docs_by_path, already_converting, ocr_candidates)
                async for event in self._process_ocr(ocr_candidates, output_dir, use_gpu, entries, summary):
                    yield event

            await cache.save_entries(entries)

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
        """Borra los `.md`/`.json` de `orphaned_paths` bajo `output_dir`, si existen.

        Usado por "forzar rescan" (`force=True`): `orphaned_paths` son rutas que
        estaban en la caché anterior pero no en el escaneo actual (fichero
        renombrado, movido o eliminado desde la última pasada) — su salida
        antigua, calculada con el mismo algoritmo que `DocumentConverter` usa al
        generarla, quedaría huérfana si no se borra aquí.
        """
        for path in orphaned_paths:
            for artifact in DocumentConverter.resolve_output_paths(path, output_dir):
                if await asyncio.to_thread(artifact.exists):
                    await asyncio.to_thread(artifact.unlink)

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
        summary: ScanSummary,
        entries: list[CacheEntry],
        ocr_candidates: list[DocumentMetadata],
    ) -> AsyncIterator[ScanEvent]:
        """Convierte cada documento, yieldeando un `FILE_CONVERTED` por unidad.

        `docs_to_process` incluye tanto ficheros nuevos/modificados (`new_set`/
        `modified_set`) como reintentos de ficheros sin cambios cuya conversión
        anterior quedó en `ERROR` (`_collect_stale_error_paths`) — estos últimos
        conservan `status=UNCHANGED`, ya que su hash no varió.

        Muta `summary`/`entries`/`ocr_candidates` in-place (son del llamador) en vez
        de devolverlos: es la forma más simple de combinar "acumula resultados" con
        "yieldea progreso" sin duplicar la lógica en dos métodos (uno con `yield`,
        otro con `return`) — contrato interno de esta clase, no una API pública.
        """
        async with DocumentConverter() as converter:
            for doc in docs_to_process:
                result = await converter.convert_document(doc, output_dir, use_ocr=False)
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
                entries.append(self._build_entry(doc, result, status, ocr_pending=result.ocr_required))
                yield ScanEvent(
                    event=ScanEventType.FILE_CONVERTED,
                    data={"path": doc.full_path, "success": result.success, "ocr_required": result.ocr_required},
                )

    @staticmethod
    def _collect_stale_error_paths(
        cached_entries: dict[str, CacheEntry],
        docs_by_path: dict[str, DocumentMetadata],
        to_process_paths: set[str],
    ) -> set[str]:
        """Devuelve las rutas de documentos sin cambios cuya conversión anterior
        quedó en `ERROR`, para reintentarlas en el siguiente escaneo normal.

        Sin esto, `get_changes()` clasifica estos ficheros como `unchanged` (su
        hash no varió) y quedarían excluidos de `docs_to_process` para siempre,
        obligando a "forzar rescan completo" (que reprocesa todo el proyecto)
        para poder reintentar un único fichero fallido.
        """
        return {
            entry.file_path
            for entry in cached_entries.values()
            if entry.conversion_status == ConversionStatus.ERROR and entry.file_path not in to_process_paths and entry.file_path in docs_by_path
        }

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
        summary: ScanSummary,
    ) -> AsyncIterator[ScanEvent]:
        """Reprocesa `ocr_candidates` con OCR, yieldeando un `OCR_PROCESSED` por unidad.

        Muta `entries`/`summary` in-place, mismo contrato que `_convert_documents`. Un
        `return` temprano en una función `async def` con `yield` es válido: simplemente
        termina el generador sin producir nada, no hace falta un generador vacío aparte.
        """
        if not ocr_candidates:
            return
        ocr_results = await OCRScheduler().process_with_ocr(ocr_candidates, output_dir, use_gpu=use_gpu)
        summary.ocr_processed = sum(1 for result in ocr_results if result.success)
        entries_by_path = {entry.file_path: entry for entry in entries}
        for doc, result in zip(ocr_candidates, ocr_results, strict=True):
            previous = entries_by_path.get(doc.full_path)
            status = previous.status if previous else DocumentStatus.UNCHANGED
            new_entry = self._build_entry(doc, result, status, ocr_pending=False)
            entries_by_path[doc.full_path] = new_entry
            yield ScanEvent(event=ScanEventType.OCR_PROCESSED, data={"path": doc.full_path, "success": result.success})
        entries[:] = list(entries_by_path.values())

    @staticmethod
    def _build_entry(doc: DocumentMetadata, result: ConversionResult, status: DocumentStatus, *, ocr_pending: bool) -> CacheEntry:
        if not result.success:
            conversion_status = ConversionStatus.ERROR
        elif ocr_pending:
            conversion_status = ConversionStatus.OCR_PENDING
        else:
            conversion_status = ConversionStatus.SUCCESS
        return CacheEntry(
            file_path=doc.full_path,
            sha256_hash=doc.sha256_hash,
            timestamp=doc.modified_time,
            status=status,
            conversion_status=conversion_status,
            error_message=result.error,
        )


__all__ = ["DeduplicationSummary", "ScanCommand", "ScanSummary"]
