"""
Orquestación de escaneo + caché + deduplicación + conversión.

Extraído de `main.py` en Fase D-2b (§2.7.3): `ScanCommand` es un módulo de
orquestación Level 3 (`architecture.instructions.md`) usado por dos entry points
distintos — el CLI (`main.py`, Fase D-1) y la interfaz web (`web/routes/scan.py`,
Fase D-2b) — así que no debe pertenecer a ninguno de los dos; vive en su propio
módulo para que ninguno dependa del otro.
"""

import asyncio
import json

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
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
    duplicate_groups: int = 0

    def render(self) -> str:
        lines = [
            f"Documentos escaneados: {self.scanned}",
            f"  nuevos: {self.new} | modificados: {self.modified} | sin cambios: {self.unchanged}",
            f"Convertidos: {self.converted} (errores: {self.conversion_errors})",
            f"Requieren OCR: {self.ocr_required} (procesados con OCR: {self.ocr_processed})",
        ]
        if self.duplicate_groups:
            lines.append(f"Grupos de duplicados resueltos: {self.duplicate_groups}")
        return "\n".join(lines)


class ScanCommand:
    """Orquesta escaneo + caché + deduplicación + conversión (Fase D-1, Fase D-2b).

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
        duplicates_dir: Path,
        folders_json: Path,
        deduplicate: bool,
        use_ocr: bool,
        use_gpu: bool,
    ) -> ScanSummary:
        """Ejecuta el pipeline y devuelve solo el resumen final (contrato sin cambios,
        Fase D-1). Consume `run_streaming()` y se queda con su evento `completed` —
        ver `§2.7.3` (Fase D-2b): la orquestación real vive ahora ahí.
        """
        summary = ScanSummary()
        async for event in self.run_streaming(
            paths, output_dir, cache_db, duplicates_dir, folders_json, deduplicate, use_ocr, use_gpu
        ):
            if event.event is ScanEventType.COMPLETED:
                summary = ScanSummary(**event.data)
        return summary

    async def run_streaming(
        self,
        paths: list[str],
        output_dir: Path,
        cache_db: Path,
        duplicates_dir: Path,
        folders_json: Path,
        deduplicate: bool,
        use_ocr: bool,
        use_gpu: bool,
    ) -> AsyncIterator[ScanEvent]:
        """Orquesta escaneo + caché + deduplicación + conversión, emitiendo progreso.

        Fase D-2b (`§2.7.3`): misma orquestación que antes vivía solo en `run()`,
        ahora factorizada aquí para que `web/routes/scan.py` pueda retransmitir cada
        evento por WebSocket sin duplicar la lógica del pipeline. Cada fase delega en
        un método privado (reduce la complejidad ciclomática de este método a la de
        "qué fases hay y en qué orden", no al detalle de cada una).
        """
        summary = ScanSummary()
        yield ScanEvent(event=ScanEventType.STARTED, data={})

        clean_paths = await self._resolve_scan_paths(paths, folders_json)

        async with DocumentScanner() as scanner:
            scan_result = await scanner.scan_folders(clean_paths)
        summary.scanned = len(scan_result.documents)

        async with CacheManager(cache_db) as cache:
            cached_entries = await cache.load_cache()
            new_files, modified_files, unchanged_files = cache.get_changes(cached_entries, scan_result.documents)
            summary.new, summary.modified, summary.unchanged = (
                len(new_files),
                len(modified_files),
                len(unchanged_files),
            )
            new_set = set(new_files)
            to_process_paths = new_set | set(modified_files)
            docs_by_path = {doc.full_path: doc for doc in scan_result.documents}
            docs_to_process = [docs_by_path[path] for path in to_process_paths if path in docs_by_path]
            yield ScanEvent(
                event=ScanEventType.SCANNED,
                data={"scanned": summary.scanned, "new": summary.new, "modified": summary.modified, "unchanged": summary.unchanged},
            )

            if deduplicate:
                docs_to_process, summary.duplicate_groups = await self._deduplicate(
                    scan_result.documents, docs_to_process, duplicates_dir
                )
                yield ScanEvent(event=ScanEventType.DEDUPLICATED, data={"duplicate_groups": summary.duplicate_groups})

            entries: list[CacheEntry] = []
            ocr_candidates: list[DocumentMetadata] = []

            async for event in self._convert_documents(docs_to_process, output_dir, new_set, summary, entries, ocr_candidates):
                yield event

            if use_ocr:
                self._collect_stale_ocr_candidates(cached_entries, docs_by_path, to_process_paths, ocr_candidates)
                async for event in self._process_ocr(ocr_candidates, output_dir, use_gpu, entries, summary):
                    yield event

            await cache.save_entries(entries)

        yield ScanEvent(event=ScanEventType.COMPLETED, data=asdict(summary))

    async def _resolve_scan_paths(self, paths: list[str], folders_json: Path) -> list[str]:
        """Valida `paths`, persiste el resultado en `folders_json`, devuelve las rutas limpias.

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
        return validation.clean_paths

    @staticmethod
    async def _deduplicate(
        documents: list[DocumentMetadata], docs_to_process: list[DocumentMetadata], duplicates_dir: Path
    ) -> tuple[list[DocumentMetadata], int]:
        """Detecta y resuelve duplicados; devuelve `(docs_to_process filtrados, nº de grupos)`."""
        dedup_manager = DeduplicationManager()
        groups = dedup_manager.find_duplicates(documents)
        if groups:
            await dedup_manager.resolve_duplicates(groups, duplicates_dir)
            discarded_paths = {doc.full_path for group in groups for doc in group.duplicates}
            docs_to_process = [doc for doc in docs_to_process if doc.full_path not in discarded_paths]
        return docs_to_process, len(groups)

    async def _convert_documents(
        self,
        docs_to_process: list[DocumentMetadata],
        output_dir: Path,
        new_set: set[str],
        summary: ScanSummary,
        entries: list[CacheEntry],
        ocr_candidates: list[DocumentMetadata],
    ) -> AsyncIterator[ScanEvent]:
        """Convierte cada documento, yieldeando un `FILE_CONVERTED` por unidad.

        Muta `summary`/`entries`/`ocr_candidates` in-place (son del llamador) en vez
        de devolverlos: es la forma más simple de combinar "acumula resultados" con
        "yieldea progreso" sin duplicar la lógica en dos métodos (uno con `yield`,
        otro con `return`) — contrato interno de esta clase, no una API pública.
        """
        async with DocumentConverter() as converter:
            for doc in docs_to_process:
                result = await converter.convert_document(doc, output_dir, use_ocr=False)
                status = DocumentStatus.NEW if doc.full_path in new_set else DocumentStatus.MODIFIED
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
        )


__all__ = ["ScanCommand", "ScanSummary"]
