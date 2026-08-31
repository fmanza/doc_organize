"""
Deduplicacion y resolucion de conflictos de version (REQ-005).
"""

import asyncio
import shutil
import uuid

from datetime import datetime, timezone
from pathlib import Path

from doc_organize.core.constants import VERSION_SUFFIX_PATTERN
from doc_organize.core.models import DeduplicationReport, DocumentMetadata, DuplicateGroup, DuplicateReason
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import safe_path_join


class DeduplicationManager:
    """Detecta duplicados exactos y conflictos de version, y los resuelve.

    `find_duplicates` es sincrono: solo compara metadatos ya calculados
    (hash, nombre, fecha de modificacion), sin tocar disco.
    `resolve_duplicates` es async porque mueve archivos en el sistema de
    ficheros. Por defecto se conserva el documento mas antiguo de cada
    grupo (`user_choice` permite sobrescribir esa eleccion).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> manager = DeduplicationManager()
        >>> groups = manager.find_duplicates(documents)
        >>> report = await manager.resolve_duplicates(groups, Path("./duplicados"))
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def find_duplicates(self, docs: list[DocumentMetadata]) -> list[DuplicateGroup]:
        """Agrupa `docs` en duplicados exactos (mismo hash) o conflictos de
        version (mismo nombre base + extension, hash distinto)."""
        groups: list[DuplicateGroup] = []
        by_hash: dict[str, list[DocumentMetadata]] = {}
        for doc in docs:
            by_hash.setdefault(doc.sha256_hash, []).append(doc)

        unique_hash_docs: list[DocumentMetadata] = []
        for hash_docs in by_hash.values():
            if len(hash_docs) > 1:
                groups.append(self._build_group(hash_docs, DuplicateReason.EXACT_DUPLICATE))
            else:
                unique_hash_docs.append(hash_docs[0])

        by_base: dict[tuple[str, str], list[DocumentMetadata]] = {}
        for doc in unique_hash_docs:
            base = self._extract_base_name(doc.display_name)
            by_base.setdefault((base, doc.extension), []).append(doc)

        for base_docs in by_base.values():
            if len(base_docs) > 1:
                groups.append(self._build_group(base_docs, DuplicateReason.VERSION_CONFLICT))

        self.logger.info(f"Deduplicación: {len(groups)} grupos detectados sobre {len(docs)} documentos")
        return groups

    async def resolve_duplicates(self, groups: list[DuplicateGroup], duplicates_dir: Path) -> DeduplicationReport:
        """Mueve los documentos descartados de cada grupo a `duplicates_dir`,
        preservando su estructura de directorios original, y escribe
        `DEDUP_REPORT.json` (solo el último run) y añade una línea a
        `DEDUP_HISTORY.jsonl` (histórico acumulado de todas las ejecuciones)."""
        duplicates_dir = Path(duplicates_dir)
        await asyncio.to_thread(duplicates_dir.mkdir, parents=True, exist_ok=True)

        exact_moved = 0
        version_resolved = 0

        for group in groups:
            keep = group.user_choice or group.canonical_doc
            to_move = [doc for doc in [group.canonical_doc, *group.duplicates] if doc.full_path != keep.full_path]
            for doc in to_move:
                await self._move_to_duplicates(Path(doc.full_path), duplicates_dir, doc.sha256_hash)
            if group.reason == DuplicateReason.EXACT_DUPLICATE:
                exact_moved += len(to_move)
            else:
                version_resolved += len(to_move)

        audit_path = duplicates_dir / "DEDUP_REPORT.json"
        report = DeduplicationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_exact_duplicates=exact_moved,
            total_version_conflicts=version_resolved,
            duplicates_folder_path=str(duplicates_dir),
            audit_json_path=str(audit_path),
            groups=groups,
        )
        await asyncio.to_thread(audit_path.write_text, report.model_dump_json(indent=2), encoding="utf-8")
        await self._append_to_history(duplicates_dir, report)
        self.logger.info(f"Deduplicación resuelta: {exact_moved} duplicados exactos, {version_resolved} conflictos de versión")
        return report

    @staticmethod
    async def _append_to_history(duplicates_dir: Path, report: DeduplicationReport) -> None:
        """Añade `report` como una línea a `DEDUP_HISTORY.jsonl` (append, nunca
        sobrescribe): a diferencia de `DEDUP_REPORT.json` (solo el último run),
        este fichero acumula todas las ejecuciones para poder consultarlas —
        tanto las lanzadas desde "Buscar duplicados" como las del formulario
        interactivo de resolución manual, ambas pasan por aquí."""
        history_path = duplicates_dir / "DEDUP_HISTORY.jsonl"
        line = report.model_dump_json() + "\n"

        def _append() -> None:
            with history_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        await asyncio.to_thread(_append)

    @staticmethod
    def _extract_base_name(display_name: str) -> str:
        stem = Path(display_name).stem
        match = VERSION_SUFFIX_PATTERN.match(stem)
        base = match.group("base") if match else stem
        return base.lower()

    @staticmethod
    def _build_group(docs: list[DocumentMetadata], reason: DuplicateReason) -> DuplicateGroup:
        canonical = min(docs, key=lambda d: d.modified_time)
        duplicates = [doc for doc in docs if doc.full_path != canonical.full_path]
        return DuplicateGroup(
            group_id=str(uuid.uuid4()),
            canonical_doc=canonical,
            duplicates=duplicates,
            reason=reason,
            user_choice=None,
        )

    async def _move_to_duplicates(self, source: Path, duplicates_dir: Path, sha256_hash: str) -> None:
        """Mueve `source` replicando su ruta absoluta (salvo la unidad/raiz)
        bajo `duplicates_dir`; si el destino ya existe, se le añade un
        sufijo con el hash para no sobrescribir nunca en silencio."""
        resolved_source = source.resolve()
        relative_parts = resolved_source.parts[1:] or (resolved_source.name,)
        target = safe_path_join(duplicates_dir, *relative_parts)
        if target.exists():
            target = target.with_name(f"{target.stem}_{sha256_hash[:8]}{target.suffix}")

        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(resolved_source), str(target))


__all__ = ["DeduplicationManager"]
