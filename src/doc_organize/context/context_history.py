"""Histórico de construcciones del contexto (`historial_contexto/CONTEXT_HISTORY.jsonl`, 1.5.0).

Cada `ContextBuilder.build()` añade una línea (`ContextBuildRecord`) con los documentos que entraron, salieron o
cambiaron de dominio o tipo de material respecto a la construcción anterior. Mismo patrón append-only y misma
tolerancia a líneas dañadas que `scan.scan_history_store` y `export.load_scan_error_history`.

Desde 1.6.0 el fichero gira al pasar de `ContextHistoryPolicy.max_bytes` (5 MB): pasa a `CONTEXT_HISTORY.1.jsonl`,
la `.1` a `.2`, etc., y se conservan `backups` copias (4). Las lecturas recorren el actual y las copias.
"""

import asyncio
import json
import os
import time

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from doc_organize.core.models import Context, ContextBuildRecord, ContextChange
from doc_organize.projects.layout import context_history_files, rotated_context_history_path
from doc_organize.utils.file_lock import exclusive_lock
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY: int = getattr(os, "O_BINARY", 0)  # Windows: sin traducir "\n" a "\r\n"

_REPLACE_ATTEMPTS = 3
_REPLACE_BACKOFF_S = 0.1


@dataclass(frozen=True)
class ContextHistoryPolicy:
    """Cuándo gira `CONTEXT_HISTORY.jsonl` y cuántas copias conserva (1.6.0).

    Attributes:
        max_bytes (int): Tamaño a partir del cual el fichero actual pasa a ser la copia `.1` antes de añadir la
            siguiente línea. Una sola línea mayor que esto se escribe igual, en un fichero nuevo.
        backups (int): Copias giradas que se conservan (`CONTEXT_HISTORY.1.jsonl` … `.<backups>.jsonl`); la más
            antigua se borra. `0` desactiva el giro: el fichero crece sin límite, como en 1.5.0.

    Example:
        >>> ContextHistoryPolicy()
        ContextHistoryPolicy(max_bytes=5000000, backups=4)
        >>> ContextHistoryPolicy(backups=0).rotates
        False
    """

    max_bytes: int = 5_000_000
    backups: int = 4

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError(f"max_bytes debe ser positivo: {self.max_bytes}")
        if self.backups < 0:
            raise ValueError(f"backups no puede ser negativo: {self.backups}")

    @property
    def rotates(self) -> bool:
        """Si esta política gira el fichero."""
        return self.backups > 0


#: Dónde está cada documento en un contexto: dominio, tipo de material y quién lo clasificó (None: sin clasificar).
_Placement = tuple[str | None, str | None, str | None]


def _placements(context: Context) -> dict[str, _Placement]:
    placements: dict[str, _Placement] = dict.fromkeys(context.unclassified_documents, (None, None, None))
    for domain in context.domains:
        for document in domain.documents:
            placements[document.source_path] = (domain.slug, document.material_type, document.classified_by)
    return placements


def diff_contexts(previous: Context | None, current: Context) -> list[ContextChange]:
    """Documentos que entraron, salieron o cambiaron de dominio o tipo de material entre `previous` y `current`.

    Un documento que solo cambia de quién lo clasificó (reglas o IA) sin cambiar de sitio no cuenta como cambio. Con
    `previous=None`, todos los documentos de `current` son `added`. Ordenados por `source_path`.

    Example:
        >>> from doc_organize.core.models import Context, Domain, DomainDocument
        >>> def ctx(slug):
        ...     doc = DomainDocument(source_path="/a.pdf", markdown_path="/a.md", json_path="/a.json",
        ...                          title="a", document_type="pdf", confidence=1.0)
        ...     return Context(project_name="P", domains=[Domain(slug=slug, name=slug, documents=[doc])],
        ...                    created_at="t", updated_at="t")
        >>> [(c.change, c.previous_domain, c.domain) for c in diff_contexts(ctx("calidad"), ctx("auditoria"))]
        [('reclassified', 'calidad', 'auditoria')]
    """
    before = _placements(previous) if previous is not None else {}
    after = _placements(current)
    changes: list[ContextChange] = []
    for source_path in sorted(before.keys() | after.keys()):
        old, new = before.get(source_path), after.get(source_path)
        if old is None and new is not None:
            changes.append(ContextChange(source_path=source_path, change="added", domain=new[0], material_type=new[1], classified_by=new[2]))
        elif new is None and old is not None:
            changes.append(ContextChange(source_path=source_path, change="removed", previous_domain=old[0], previous_material_type=old[1]))
        elif old is not None and new is not None and old[:2] != new[:2]:
            changes.append(
                ContextChange(
                    source_path=source_path,
                    change="reclassified",
                    previous_domain=old[0],
                    domain=new[0],
                    previous_material_type=old[1],
                    material_type=new[1],
                    classified_by=new[2],
                )
            )
    return changes


def build_record(previous: Context | None, current: Context) -> ContextBuildRecord:
    """`ContextBuildRecord` de `current` comparado con `previous` (la construcción anterior, o None)."""
    return ContextBuildRecord(
        built_at=current.updated_at,
        previous_built_at=previous.updated_at if previous is not None else None,
        project_name=current.project_name,
        built_with_version=current.built_with_version,
        taxonomy_manifest_used=current.taxonomy_manifest_used,
        ai_classification_model=current.ai_classification_model,
        ai_enrichment_model=current.ai_enrichment_model,
        classified=sum(len(domain.documents) for domain in current.domains),
        unclassified=len(current.unclassified_documents),
        changes=diff_contexts(previous, current),
    )


def _append_line(history_path: Path, line: bytes) -> None:
    """Una sola escritura con `O_APPEND`, sin seguir enlaces, y `fsync` antes de soltar el bloqueo."""
    fd = os.open(history_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW | _O_BINARY, 0o644)
    try:
        written = os.write(fd, line)
        while written < len(line):  # escritura parcial: rara, pero posible en red
            written += os.write(fd, line[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_with_retry(source: Path, target: Path) -> None:
    """`os.replace` con reintentos cortos: en Windows falla con `PermissionError` mientras un lector tiene abierto el
    fichero."""
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_BACKOFF_S * attempt)


def _rotate(history_path: Path, backups: int) -> None:
    """`history_path` → `.1`, `.1` → `.2`, …; se borran las copias que pasarían de `backups`. Bajo el bloqueo."""
    for stale in context_history_files(history_path):
        if stale != history_path and int(stale.stem.rsplit(".", 1)[1]) >= backups:
            stale.unlink(missing_ok=True)
    for index in range(backups - 1, 0, -1):
        source = rotated_context_history_path(history_path, index)
        if source.exists():
            _replace_with_retry(source, rotated_context_history_path(history_path, index + 1))
    _replace_with_retry(history_path, rotated_context_history_path(history_path, 1))


def _needs_rotation(history_path: Path, line_size: int, policy: ContextHistoryPolicy) -> bool:
    if not policy.rotates:
        return False
    try:
        size = history_path.stat().st_size
    except FileNotFoundError:
        return False
    return size > 0 and size + line_size > policy.max_bytes


async def append_context_build(history_path: Path, record: ContextBuildRecord, policy: ContextHistoryPolicy | None = None) -> None:
    """Añade `record` como una línea JSON a `history_path` (crea la carpeta si falta).

    Desde 1.6.0 la escritura se hace bajo un bloqueo entre procesos (`<history_path>.lock`), para que dos construcciones
    del mismo proyecto en procesos o equipos distintos no intercalen sus líneas, y el fichero gira según `policy`
    (`ContextHistoryPolicy()` si es `None`). Si el giro falla (p. ej. un lector tiene el fichero abierto en Windows),
    se avisa y la línea se añade igualmente al fichero actual.

    Raises:
        OSError: Si no se puede escribir, o `TimeoutError` (un `OSError`) si otro proceso mantiene el bloqueo más de
            unos segundos. `ContextBuilder` lo registra como aviso y la construcción no falla.
    """
    policy = policy or ContextHistoryPolicy()
    await asyncio.to_thread(history_path.parent.mkdir, parents=True, exist_ok=True)
    line = (record.model_dump_json() + "\n").encode("utf-8")

    def _append() -> None:
        with exclusive_lock(history_path):
            if _needs_rotation(history_path, len(line), policy):
                try:
                    _rotate(history_path, policy.backups)
                except OSError as exc:
                    logger.warning(f"No se pudo girar '{history_path}'; la construcción se añade al fichero actual: {exc}")
            _append_line(history_path, line)

    await asyncio.to_thread(_append)


def _read_records(path: Path) -> list[ContextBuildRecord]:
    """Líneas válidas de `path` en orden de escritura; `[]` si no existe (p. ej. lo acaba de girar otro proceso)."""
    records: list[ContextBuildRecord] = []
    try:
        with path.open(encoding="utf-8") as lines:
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    records.append(ContextBuildRecord.model_validate_json(line))
                except (json.JSONDecodeError, ValidationError):
                    logger.warning(f"Línea inválida en '{path}'; se ignora.")
    except FileNotFoundError:
        return []
    return records


def list_context_builds(history_path: Path, *, include_rotated: bool = True) -> list[ContextBuildRecord]:
    """Construcciones de `history_path`, las más recientes primero; `[]` si no existe.

    Desde 1.6.0 también lee las copias giradas (`CONTEXT_HISTORY.1.jsonl`…), salvo con `include_rotated=False`. Una
    línea inválida (p. ej. un corte a mitad de escritura) se ignora con un aviso en vez de impedir leer el resto. No toma
    el bloqueo: si otro proceso gira el fichero mientras se lee, puede faltar o repetirse alguna construcción en esa
    lectura (el historial en disco no se altera).

    Example:
        >>> list_context_builds(Path("/ruta/que/no/existe/CONTEXT_HISTORY.jsonl"))
        []
    """
    files = context_history_files(history_path) if include_rotated else [history_path]
    records = [record for path in files for record in _read_records(path)]
    records.reverse()
    return records


def history_file_set(history_paths: Iterable[Path]) -> list[Path]:
    """Todos los ficheros (actual y copias giradas) de `history_paths`, sin repetir, en orden de aparición.

    Así, pasar a la vez el actual y sus copias (p. ej. de `ProjectLayout.context_history_files()`) no duplica nada.
    """
    files: dict[str, Path] = {}
    for history_path in history_paths:
        for path in context_history_files(history_path) or [history_path]:
            files.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return list(files.values())


__all__ = [
    "ContextHistoryPolicy",
    "append_context_build",
    "build_record",
    "diff_contexts",
    "history_file_set",
    "list_context_builds",
]
