"""
Cola de revisión (2.0.0, F6): qué documentos debería mirar una persona, y por qué, a partir de un `Context`.

No cambia nada ni llama a nadie: lee el contexto y devuelve una lista ordenada por prioridad. Lo que una persona ya
decidió (`classified_by="human"`) no vuelve a la cola, salvo que su decisión haya quedado desfasada.

| Motivo | Cuándo |
|---|---|
| `stale_decision` | Una decisión no se aplicó (el original o el catálogo cambiaron) |
| `unclassified` | Sin clasificar: sin conversión, o con el eje que organiza en carpeta vacío |
| `rules_ai_disagreement` | La IA propuso otro dominio que las reglas |
| `unverified_evidence` | La cita de la IA no aparece en el documento (D10) |
| `low_confidence` | Un valor por debajo del umbral de su eje |
| `unconfirmed_version` | Un grupo de versiones cuya vigente no ha confirmado nadie (F5) |
| `reviewer_proposal` | El revisor (`ReviewAgent`, G6) propone una decisión: aceptarla o no es de una persona |
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from doc_organize.context.evaluation import document_keys
from doc_organize.core.models import AxisValue, Context, DomainDocument, TaxonomyAxis

ReviewReason = Literal[
    "stale_decision", "unclassified", "rules_ai_disagreement", "unverified_evidence", "low_confidence", "unconfirmed_version", "reviewer_proposal"
]


class ReviewProposalLike(Protocol):
    """Lo que la cola lee de una propuesta del revisor (`ReviewProposal`)."""

    document_key: str
    action: str
    axes: dict[str, list[str]]
    rationale: str


#: Orden de la cola: lo primero, lo que más urge.
REVIEW_PRIORITY: dict[ReviewReason, int] = {
    "stale_decision": 0,
    "unclassified": 1,
    "rules_ai_disagreement": 2,
    "unverified_evidence": 3,
    "low_confidence": 4,
    "unconfirmed_version": 5,
    "reviewer_proposal": 6,
}


class ReviewItem(BaseModel):
    """Un motivo para revisar un documento.

    Attributes:
        document_key (str): Clave del documento (`document_key`), la de las decisiones.
        source_path (str | None): Ruta del original en el contexto (`None` en una decisión desfasada de un documento
            que ya no está).
        reason (ReviewReason): Por qué.
        axis (str | None): Eje afectado, si es de uno.
        value (str | None): Valor afectado, si es de uno.
        confidence (float | None): Su confianza, si la tiene.
        detail (str | None): Explicación breve (la cita no verificada, el dominio que propuso la IA...).
        priority (int): `REVIEW_PRIORITY` del motivo.
    """

    document_key: str
    source_path: str | None = None
    reason: ReviewReason
    axis: str | None = None
    value: str | None = None
    confidence: float | None = None
    detail: str | None = None
    priority: int = Field(default=0, ge=0)


def review_queue(context: Context, *, roots: Sequence[str] | None = None, proposals: Sequence[ReviewProposalLike] = ()) -> list[ReviewItem]:
    """Lo que habría que revisar en `context`, por prioridad (`REVIEW_PRIORITY`) y, dentro de ella, por documento.

    Args:
        context: El contexto (de `ContextRegistry.load_context` o recién construido).
        roots: Raíces de escaneo para las claves (por defecto, la carpeta común de todos los originales), como en
            `ContextBuilder.build(scan_roots=)`.
        proposals: Propuestas del revisor (`ReviewResult.proposals`) que añadir a la cola (`reviewer_proposal`).

    Example:
        >>> from doc_organize.core.models import DecisionIssue
        >>> context = Context(project_name="p", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        ...     stale_decisions=[DecisionIssue(decision_id="d1", document_key="ENS/plan.pdf", reason="source_changed")])
        >>> item = review_queue(context)[0]
        >>> print(item.reason, item.document_key)
        stale_decision ENS/plan.pdf
    """
    documents = [(domain.slug, document) for domain in context.domains for document in domain.documents]
    keys = document_keys([document.source_path for _, document in documents] + [detail.source_path for detail in context.unclassified_details], roots)
    axes = {axis.key: axis for axis in context.taxonomy_axes}
    folder = next((axis for axis in context.taxonomy_axes if axis.organizes == "folder"), None)
    path_by_key = {key: path for path, key in keys.items()}

    items = [
        _item(
            "stale_decision",
            issue.document_key,
            path_by_key.get(issue.document_key),
            detail=f"{issue.reason}" + (f": {issue.detail}" if issue.detail else ""),
        )
        for issue in context.stale_decisions
    ]
    for group in context.version_groups:
        if not group.confirmed:
            versions = ", ".join(f"{version}" for version in group.versions)
            items.append(
                _item(
                    "unconfirmed_version",
                    keys.get(group.current, group.current),
                    group.current,
                    detail=f"Versiones {versions}; vigente propuesta: la más alta",
                )
            )
    for detail in context.unclassified_details:
        items.append(_item("unclassified", keys[detail.source_path], detail.source_path, axis=folder.key if folder else None, detail=detail.reason))
    for domain_slug, document in documents:
        items.extend(_document_items(document, domain_slug, keys[document.source_path], axes, folder, context.ai_fallback_threshold))
    for proposal in proposals:
        axis = next(iter(proposal.axes), None)
        items.append(
            _item(
                "reviewer_proposal",
                proposal.document_key,
                path_by_key.get(proposal.document_key),
                axis=axis,
                value=", ".join(proposal.axes[axis]) if axis else None,
                detail=f"{proposal.action}: {proposal.rationale}"[:500],
            )
        )
    return sorted(items, key=lambda item: (item.priority, item.document_key, item.axis or "", item.value or ""))


def _document_items(
    document: DomainDocument,
    domain_slug: str,
    key: str,
    axes: dict[str, TaxonomyAxis],
    folder: TaxonomyAxis | None,
    default_threshold: float,
) -> list[ReviewItem]:
    items: list[ReviewItem | None] = []
    if folder is not None:
        domain_values = document.classification.axes.get(folder.key, [])
        if not domain_values:
            items.append(_item("unclassified", key, document.source_path, axis=folder.key))
        elif document.ai_domain and document.ai_domain != domain_slug and all(value.classified_by != "human" for value in domain_values):
            items.append(
                _item(
                    "rules_ai_disagreement",
                    key,
                    document.source_path,
                    axis=folder.key,
                    value=domain_slug,
                    confidence=document.ai_confidence,
                    detail=f"La IA propuso «{document.ai_domain}»",
                )
            )
    for axis_key, values in document.classification.axes.items():
        axis = axes.get(axis_key)
        threshold = axis.threshold if axis is not None and axis.threshold is not None else default_threshold
        items.extend(_value_item(value, axis_key, threshold, key, document.source_path) for value in values if value.classified_by != "human")
    return [item for item in items if item is not None]


def _value_item(value: AxisValue, axis_key: str, threshold: float, key: str, source_path: str) -> ReviewItem | None:
    """Un valor de las reglas o la IA que hay que revisar: cita no verificada o confianza baja; `None` si ninguna."""
    if value.evidence_verified is False:
        return _item("unverified_evidence", key, source_path, axis=axis_key, value=value.slug, confidence=value.confidence, detail=value.evidence)
    if value.confidence < threshold:
        return _item("low_confidence", key, source_path, axis=axis_key, value=value.slug, confidence=value.confidence)
    return None


def _item(
    reason: ReviewReason,
    key: str,
    source_path: str | None,
    *,
    axis: str | None = None,
    value: str | None = None,
    confidence: float | None = None,
    detail: str | None = None,
) -> ReviewItem:
    return ReviewItem(
        document_key=key,
        source_path=source_path,
        reason=reason,
        axis=axis,
        value=value,
        confidence=confidence,
        detail=detail,
        priority=REVIEW_PRIORITY[reason],
    )


__all__ = ["REVIEW_PRIORITY", "ReviewItem", "ReviewReason", "review_queue"]
