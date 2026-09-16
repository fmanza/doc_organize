"""
Deduplicacion y resolucion de conflictos de version (REQ-005).
"""

import asyncio
import shutil
import uuid

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from rapidfuzz import fuzz, process, utils

from doc_organize.core.constants import DEDUP_HISTORY_JSONL_NAME, DEDUP_REPORT_JSON_NAME, VERSION_SUFFIX_PATTERN
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
        >>> import asyncio, tempfile
        >>> async def main():
        ...     source_dir = Path(tempfile.mkdtemp())
        ...     original = source_dir / "a.pdf"
        ...     copia = source_dir / "a_copy.pdf"
        ...     original.write_bytes(b"contenido-identico")
        ...     copia.write_bytes(b"contenido-identico")
        ...     documents = [
        ...         DocumentMetadata(full_path=str(original), display_name="a.pdf", extension="pdf",
        ...             size_bytes=19, modified_time=1.0, sha256_hash="hash-igual"),
        ...         DocumentMetadata(full_path=str(copia), display_name="a_copy.pdf", extension="pdf",
        ...             size_bytes=19, modified_time=2.0, sha256_hash="hash-igual"),
        ...     ]
        ...     manager = DeduplicationManager()
        ...     groups = manager.find_duplicates(documents)
        ...     duplicates_dir = Path(tempfile.mkdtemp())
        ...     report = await manager.resolve_duplicates(groups, duplicates_dir)
        ...     return report.total_exact_duplicates
        >>> asyncio.run(main())
        1
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def find_duplicates(self, docs: list[DocumentMetadata], fuzzy_threshold: int | None = None) -> list[DuplicateGroup]:
        """Agrupa `docs` en duplicados exactos (mismo hash), conflictos de
        version (mismo nombre base + extension, hash distinto) y, si se indica
        `fuzzy_threshold`, similitud aproximada de nombre sobre lo que quede sin
        agrupar tras las dos pasadas anteriores.

        `fuzzy_threshold` es `None` por defecto (retrocompatible, cero
        regresiones): sin él, el comportamiento es idéntico al de antes de esta
        tercera pasada. Cuando se indica (0-100, score RapidFuzz normalizado),
        cada documento aun sin agrupar se compara por `display_name` contra el
        resto vía `rapidfuzz.process.cdist` (vectorizado en C, no un doble bucle
        Python) y se agrupan por componentes conexas del grafo de similitud
        (pares con score >= `fuzzy_threshold`), sin exigir que TODOS los pares
        de un grupo superen el umbral entre sí -- ver `_build_fuzzy_groups()`.

        Los grupos `FUZZY_NAME_MATCH` resultantes nunca deben pasar por la
        resolución automática masiva de "Buscar duplicados"
        (`ScanCommand.deduplicate_streaming`, que llama a este método sin
        `fuzzy_threshold`): al ser coincidencias probabilísticas por nombre,
        solo se resuelven desde el formulario interactivo de "Revisar
        Duplicados", donde el usuario elige explícitamente qué archivo
        conservar por grupo.
        """
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

        if fuzzy_threshold is not None:
            grouped_paths = {doc.full_path for group in groups for doc in [group.canonical_doc, *group.duplicates]}
            remaining = [doc for doc in unique_hash_docs if doc.full_path not in grouped_paths]
            groups.extend(self._build_fuzzy_groups(remaining, fuzzy_threshold))

        self.logger.info(f"Deduplicación: {len(groups)} grupos detectados sobre {len(docs)} documentos")
        return groups

    async def move_group(self, group: DuplicateGroup, duplicates_dir: Path) -> tuple[int, int, list[str]]:
        """Mueve los documentos descartados de un único `group` a `duplicates_dir`.

        Devuelve `(duplicados_exactos_movidos, conflictos_de_version_resueltos,
        rutas_fallidas)` de este grupo (0/`[]` en lo que no aplique, según
        `group.reason`). Extraído de `resolve_duplicates()` (que lo reutiliza en
        su propio bucle) para que `ScanCommand.deduplicate_streaming()` pueda
        yieldear progreso por grupo sin duplicar la lógica de movimiento --
        mismo criterio que la relación entre `DocumentConverter.convert_document()`
        (por documento) y el bucle de `ScanCommand._convert_documents()`.

        Resiliencia por fichero (AUDIT_CODE, sesión 2026-09-04): si mover un
        documento falla (`OSError` -- permiso denegado, fichero ausente/bloqueado,
        colisión doble tras sufijo de hash), se registra en `rutas_fallidas` y se
        sigue con el resto del grupo, en vez de abortar el grupo entero (y, en
        cascada, el resto del lote) por un único fichero -- mismo criterio que
        `DocumentConverter.convert_document()` aísla un documento del resto del
        batch de conversión.
        """
        keep = group.user_choice or group.canonical_doc
        to_move = [doc for doc in [group.canonical_doc, *group.duplicates] if doc.full_path != keep.full_path]
        moved = 0
        failed_paths: list[str] = []
        for doc in to_move:
            try:
                await self._move_to_duplicates(Path(doc.full_path), duplicates_dir, doc.sha256_hash)
            except OSError as exc:
                self.logger.warning(f"No se pudo mover '{doc.full_path}' a duplicados: {exc}")
                failed_paths.append(doc.full_path)
                continue
            moved += 1
        if group.reason == DuplicateReason.EXACT_DUPLICATE:
            return moved, 0, failed_paths
        return 0, moved, failed_paths

    async def finalize_report(
        self,
        groups: list[DuplicateGroup],
        duplicates_dir: Path,
        exact_moved: int,
        version_resolved: int,
        started_at: datetime | None = None,
        failed_paths: list[str] | None = None,
    ) -> DeduplicationReport:
        """Construye el `DeduplicationReport` de una resolución ya completada
        (todos los grupos ya movidos vía `move_group`), escribe
        `DEDUP_REPORT.json` (solo el último run) y añade una línea a
        `DEDUP_HISTORY.jsonl` (histórico acumulado de todas las ejecuciones).

        Público (no un detalle interno de `resolve_duplicates()`):
        `ScanCommand.deduplicate_streaming()` también lo llama, tras su propio
        bucle con progreso por grupo -- mismo criterio de "no importar símbolos
        privados entre módulos" ya establecido en el proyecto (ver
        `web/scan_errors_data.py`).

        `started_at` es opcional (compatibilidad con llamadores no adaptados):
        cuando se pasa, `duration_seconds` cubre desde ahí hasta que este método
        termina -- el llamador debe capturarlo *antes* de detectar los grupos
        (`find_duplicates`/re-escaneo), no solo antes de mover ficheros, para que
        la duración mostrada en pantalla represente la operación completa
        ("Buscar duplicados"), igual que `ScanRunReport` cubre el run entero de
        Escanear. Si se omite, `DeduplicationReport.duration_seconds` queda en
        `None` (sin dato) en vez de medir solo el movimiento de ficheros, que
        sería una duración parcial engañosa.
        """
        finished_at = datetime.now(UTC)
        audit_path = duplicates_dir / DEDUP_REPORT_JSON_NAME
        report = DeduplicationReport(
            timestamp=finished_at.isoformat(),
            total_exact_duplicates=exact_moved,
            total_version_conflicts=version_resolved,
            duplicates_folder_path=str(duplicates_dir),
            started_at=started_at.isoformat() if started_at else None,
            duration_seconds=(finished_at - started_at).total_seconds() if started_at else None,
            failed_paths=failed_paths or [],
            audit_json_path=str(audit_path),
            groups=groups,
        )
        await asyncio.to_thread(audit_path.write_text, report.model_dump_json(indent=2), encoding="utf-8")
        await self._append_to_history(duplicates_dir, report)
        return report

    async def resolve_duplicates(self, groups: list[DuplicateGroup], duplicates_dir: Path, started_at: datetime | None = None) -> DeduplicationReport:
        """Mueve los documentos descartados de cada grupo a `duplicates_dir`,
        preservando su estructura de directorios original, y escribe
        `DEDUP_REPORT.json` (solo el último run) y añade una línea a
        `DEDUP_HISTORY.jsonl` (histórico acumulado de todas las ejecuciones).

        Composición de `move_group()` (bucle, sin progreso) + `finalize_report()`
        (persistencia) -- la vía "todo de una vez" usada por el resolver
        interactivo (`web/routes/duplicates.py`). `ScanCommand.
        deduplicate_streaming()` usa las mismas dos primitivas por separado, con
        eventos de progreso entre medias.

        `started_at` es opcional, ver `finalize_report()`.
        """
        duplicates_dir = Path(duplicates_dir)
        await asyncio.to_thread(duplicates_dir.mkdir, parents=True, exist_ok=True)

        exact_moved = 0
        version_resolved = 0
        failed_paths: list[str] = []
        for group in groups:
            exact, version, group_failed = await self.move_group(group, duplicates_dir)
            exact_moved += exact
            version_resolved += version
            failed_paths.extend(group_failed)

        report = await self.finalize_report(groups, duplicates_dir, exact_moved, version_resolved, started_at, failed_paths=failed_paths)
        self.logger.info(
            f"Deduplicación resuelta: {exact_moved} duplicados exactos, {version_resolved} conflictos de versión"
            + (f", {len(failed_paths)} fallidos" if failed_paths else "")
        )
        return report

    @staticmethod
    async def _append_to_history(duplicates_dir: Path, report: DeduplicationReport) -> None:
        """Añade `report` como una línea a `DEDUP_HISTORY.jsonl` (append, nunca
        sobrescribe): a diferencia de `DEDUP_REPORT.json` (solo el último run),
        este fichero acumula todas las ejecuciones para poder consultarlas —
        tanto las lanzadas desde "Buscar duplicados" como las del formulario
        interactivo de resolución manual, ambas pasan por aquí."""
        history_path = duplicates_dir / DEDUP_HISTORY_JSONL_NAME
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
    def _build_fuzzy_groups(docs: list[DocumentMetadata], fuzzy_threshold: int) -> list[DuplicateGroup]:
        """Agrupa `docs` (ya sin duplicados exactos ni conflictos de versión) por
        similitud aproximada de `display_name`, normalizando cada nombre antes de
        comparar: se quita la extensión (`Path.stem`) y se pasa por
        `rapidfuzz.utils.default_process` (pliega a minúsculas y convierte
        cualquier separador no alfanumérico -- `_`, `-`, espacios repetidos -- en
        un único espacio). Sin esto, dos nombres que solo difieren en el
        separador (`informe-ventas` vs `informe_ventas`) o que comparten
        extensión larga penalizan el score sin motivo real.

        Usa `fuzz.WRatio` como scorer -- no `fuzz.ratio` (distancia Indel/
        Levenshtein pura) -- porque `WRatio` combina ratio simple y
        partial-ratio según la diferencia de longitud entre cadenas: capta el
        caso común de nombres de fichero con sufijos añadidos (copias,
        revisiones, fechas), donde uno es sustancialmente prefijo/substring del
        otro y `ratio` penaliza fuerte solo por la diferencia de longitud.

        Usa `rapidfuzz.process.cdist` para calcular la matriz de scores completa
        de una vez (vectorizado en C), y `numpy` para extraer de ella, también
        vectorizado, los pares con score >= `fuzzy_threshold` -- ningún doble
        bucle Python sobre pares de nombres, solo sobre las aristas ya filtradas.
        Esos pares se agrupan por componentes conexas (union-find): dos
        documentos terminan en el mismo grupo si hay una cadena de pares que los
        conecta, sin exigir que absolutamente todos los pares del grupo superen
        el umbral entre sí (REQ de negocio: no asumir transitividad estricta).
        """
        if len(docs) < 2:
            return []

        names = [utils.default_process(Path(doc.display_name).stem) for doc in docs]
        score_matrix = process.cdist(names, names, scorer=fuzz.WRatio, score_cutoff=fuzzy_threshold, workers=-1)

        parent = list(range(len(docs)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(a: int, b: int) -> None:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_a] = root_b

        above_threshold = np.triu(score_matrix >= fuzzy_threshold, k=1)
        for i, j in np.argwhere(above_threshold).tolist():
            union(i, j)

        components: dict[int, list[DocumentMetadata]] = {}
        for index, doc in enumerate(docs):
            components.setdefault(find(index), []).append(doc)

        return [DeduplicationManager._build_group(members, DuplicateReason.FUZZY_NAME_MATCH) for members in components.values() if len(members) > 1]

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
        sufijo con el hash para no sobrescribir nunca en silencio.

        Si el destino ya sufijado con el hash **también** existe (AUDIT_CODE,
        sesión 2026-09-03), no se reintenta ni se sobrescribe: `shutil.move` cae
        a un fallback copy+unlink cuando `os.rename` falla por destino existente
        y ese fallback sobrescribe sin avisar en Windows — se rechaza
        explícitamente en vez de arriesgar esa pérdida silenciosa de datos.
        """
        resolved_source = source.resolve()
        relative_parts = resolved_source.parts[1:] or (resolved_source.name,)
        target = safe_path_join(duplicates_dir, *relative_parts)
        if target.exists():
            target = target.with_name(f"{target.stem}_{sha256_hash[:8]}{target.suffix}")
            if target.exists():
                raise FileExistsError(
                    f"No se pudo mover '{resolved_source}' a duplicados: el destino '{target}' ya existe "
                    "incluso tras añadir el sufijo de hash (colisión doble)."
                )

        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(resolved_source), str(target))


__all__ = ["DeduplicationManager"]
