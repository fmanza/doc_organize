"""Histórico de construcciones del contexto (`historial_contexto/CONTEXT_HISTORY.jsonl`, 1.5.0).

Cada `ContextBuilder.build()` añade una línea (`ContextBuildRecord`) con los documentos que entraron, salieron o
cambiaron de dominio o tipo de material respecto a la construcción anterior. Mismo patrón append-only y misma
tolerancia a líneas dañadas que `scan.scan_history_store` y `export.load_scan_error_history`.
"""

import asyncio
import json

from pathlib import Path

from pydantic import ValidationError

from doc_organize.core.models import Context, ContextBuildRecord, ContextChange
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

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


async def append_context_build(history_path: Path, record: ContextBuildRecord) -> None:
    """Añade `record` como una línea JSON a `history_path` (crea la carpeta si falta)."""
    await asyncio.to_thread(history_path.parent.mkdir, parents=True, exist_ok=True)

    def _append() -> None:
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    await asyncio.to_thread(_append)


def list_context_builds(history_path: Path) -> list[ContextBuildRecord]:
    """Construcciones de `history_path`, las más recientes primero; `[]` si no existe.

    Una línea inválida (p. ej. un corte a mitad de escritura) se ignora con un aviso en vez de impedir leer el resto.

    Example:
        >>> list_context_builds(Path("/ruta/que/no/existe/CONTEXT_HISTORY.jsonl"))
        []
    """
    if not history_path.is_file():
        return []
    records: list[ContextBuildRecord] = []
    with history_path.open(encoding="utf-8") as lines:
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(ContextBuildRecord.model_validate_json(line))
            except (json.JSONDecodeError, ValidationError):
                logger.warning(f"Línea inválida en '{history_path}'; se ignora.")
    records.reverse()
    return records


__all__ = ["append_context_build", "build_record", "diff_contexts", "list_context_builds"]
