"""
Decisiones de personas sobre la clasificación (2.0.0, F6).

Una persona puede **confirmar** la clasificación de un documento, **fijar** los valores de un eje o **excluirlo** del
contexto. Las decisiones se guardan en `<raíz>/.doc_organize/decisions.json` (`ClassificationDecisionStore`, escritura
atómica y bloqueo entre procesos) y `ContextBuilder.build` las aplica en cada construcción, después de las reglas y
antes de la IA: lo decidido queda con `classified_by="human"` y ni las reglas ni la IA lo cambian.

Una decisión deja de aplicarse, y queda para revisarla, si el original cambió desde entonces (`source_sha256`
distinto) o si su eje o su valor ya no están en el catálogo (`Context.stale_decisions`); si el documento no está en la
construcción, queda en `Context.orphan_decisions`. Una decisión nueva sobre lo mismo sustituye a la anterior, que pasa
al historial (`revoked`).
"""

from __future__ import annotations

import asyncio
import json
import uuid

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from doc_organize.context.evaluation import GoldLabel, GoldStandard, document_keys
from doc_organize.core.models import (
    AxisValue,
    ClassificationDecision,
    ConversionResult,
    DecisionIssue,
    DecisionIssueReason,
    DomainDocument,
    TaxonomyAxis,
    TaxonomyManifest,
)
from doc_organize.utils.atomic_write import write_text_atomic
from doc_organize.utils.file_lock import exclusive_lock
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

#: Fichero de decisiones del proyecto, relativo a su raíz.
DECISIONS_FILE = Path(".doc_organize") / "decisions.json"
_SCHEMA = 1


class ClassificationDecisionStore:
    """Las decisiones de un proyecto: las vigentes y el historial de revocadas.

    Example:
        >>> import asyncio, tempfile
        >>> store = ClassificationDecisionStore(tempfile.mkdtemp())
        >>> decision = asyncio.run(store.add(ClassificationDecision(document_key="a.pdf", action="exclude", author="ana")))
        >>> [d.document_key for d in asyncio.run(store.load())], len(decision.id)
        (['a.pdf'], 32)
    """

    def __init__(self, project_root: str | Path) -> None:
        self.path = Path(project_root) / DECISIONS_FILE

    async def load(self) -> list[ClassificationDecision]:
        """Las decisiones vigentes, en el orden en que se tomaron (vacío si no hay fichero)."""
        return (await asyncio.to_thread(self._read))[0]

    async def revoked(self) -> list[ClassificationDecision]:
        """El historial: las decisiones revocadas o sustituidas, con `revoked_at`, `revoked_by` y `revoke_reason`."""
        return (await asyncio.to_thread(self._read))[1]

    async def add(self, decision: ClassificationDecision) -> ClassificationDecision:
        """Guarda `decision` (con `id` nuevo si no lo trae). Sustituye a las vigentes que decidían lo mismo: todas las del
        documento si es `confirm` o `exclude`; si es `set_axis`, la del mismo eje y un `exclude` (un `confirm` anterior
        se conserva: el `set_axis` se aplica después y gana en su eje)."""
        saved = decision if decision.id else decision.model_copy(update={"id": uuid.uuid4().hex})
        await asyncio.to_thread(self._update, lambda active: _replace(active, saved))
        return saved

    async def revoke(self, decision_id: str, *, author: str | None = None, reason: str | None = None) -> bool:
        """Revoca una decisión vigente (pasa al historial). `False` si no había ninguna con ese `id`."""
        found = False

        def change(active: list[ClassificationDecision]) -> tuple[list[ClassificationDecision], list[ClassificationDecision]]:
            nonlocal found
            keep = [decision for decision in active if decision.id != decision_id]
            gone = [_revoked(decision, author, reason) for decision in active if decision.id == decision_id]
            found = bool(gone)
            return keep, gone

        await asyncio.to_thread(self._update, change)
        return found

    def _read(self) -> tuple[list[ClassificationDecision], list[ClassificationDecision]]:
        if self.path.is_symlink() or not self.path.is_file():
            return [], []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return (
            [ClassificationDecision.model_validate(item) for item in data.get("decisions", [])],
            [ClassificationDecision.model_validate(item) for item in data.get("revoked", [])],
        )

    def _update(self, change: Callable[[list[ClassificationDecision]], tuple[list[ClassificationDecision], list[ClassificationDecision]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            active, revoked = self._read()
            active, gone = change(active)
            payload = {
                "schema": _SCHEMA,
                "decisions": [decision.model_dump(mode="json", exclude_none=True) for decision in active],
                "revoked": [decision.model_dump(mode="json", exclude_none=True) for decision in [*revoked, *gone]],
            }
            write_text_atomic(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def gold_from_decisions(decisions: Sequence[ClassificationDecision]) -> GoldStandard:
    """Una referencia a partir de lo que decidieron las personas (2.0.0, G3): cada `confirm` y `set_axis` da los valores
    correctos de sus ejes (los `exclude` no cuentan).

    Example:
        >>> gold = gold_from_decisions([ClassificationDecision(document_key="a.pdf", action="set_axis", axes={"domains": ["calidad"]})])
        >>> gold.labels[0].axes == {"domains": ["calidad"]}
        True
    """
    labels: dict[str, dict[str, list[str]]] = {}
    for decision in decisions:
        if decision.action != "exclude":
            labels.setdefault(decision.document_key, {}).update(decision.axes)
    return GoldStandard(labels=[GoldLabel(document=key, axes=axes) for key, axes in labels.items()])


@dataclass
class DecisionOutcome:
    """Lo que pasó al aplicar las decisiones en una construcción."""

    applied: int = 0
    stale: list[DecisionIssue] = field(default_factory=list)
    orphan: list[DecisionIssue] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    #: Por documento (`id()` del `DomainDocument`), los ejes que decidió una persona: la IA no los toca.
    locked: dict[int, set[str]] = field(default_factory=dict)


def not_applied_without_manifest(decisions: Sequence[ClassificationDecision]) -> DecisionOutcome:
    """Sin manifiesto no se aplican decisiones: todas quedan en `stale` con `no_manifest`."""
    return DecisionOutcome(stale=[DecisionIssue(decision_id=d.id, document_key=d.document_key, reason="no_manifest") for d in decisions])


def apply_decisions(
    decisions: Sequence[ClassificationDecision],
    classified: dict[str, list[DomainDocument]],
    unclassified: list[ConversionResult],
    manifest: TaxonomyManifest,
    *,
    slugify: Callable[[str], str],
    roots: Sequence[str] | None = None,
) -> DecisionOutcome:
    """Aplica `decisions` a `classified` y `unclassified` (in-place) tras las reglas: mueve de dominio, fija ejes con
    `classified_by="human"` y saca los excluidos. Devuelve lo aplicado, lo desfasado, lo huérfano y los ejes bloqueados.

    Args:
        decisions: Decisiones vigentes, en el orden en que se tomaron.
        classified: Documentos por dominio (incluido el de «sin clasificar»); los que quedan vacíos se quitan.
        unclassified: Documentos sin `.json` (solo se pueden excluir).
        manifest: Catálogo de la construcción (los valores decididos tienen que estar en él).
        slugify: Cómo se sanean los slugs de los ejes que organizan (como las reglas).
        roots: Raíces de escaneo para las claves (por defecto, la carpeta común de todos los originales).
    """
    outcome = DecisionOutcome()
    documents = {id(document): (slug, document) for slug, docs in classified.items() for document in docs}
    paths = [document.source_path for _, document in documents.values()] + [result.source_path for result in unclassified]
    keys = document_keys(paths, roots)
    by_key: dict[str, DomainDocument | ConversionResult] = {keys[document.source_path]: document for _, document in documents.values()}
    by_key.update({keys[result.source_path]: result for result in unclassified})
    current_slug = {id(document): slug for slug, document in documents.values()}

    for decision in decisions:
        target = by_key.get(decision.document_key)
        issue = _issue(decision, target, manifest, slugify)
        if issue is not None or target is None:
            if issue is not None:
                (outcome.orphan if issue.reason == "missing_document" else outcome.stale).append(issue)
            continue
        if decision.action == "exclude":
            _exclude(target, classified, unclassified, current_slug)
            outcome.excluded.append(target.source_path)
            by_key.pop(decision.document_key)
        else:
            assert isinstance(target, DomainDocument)  # `_issue` lo comprobó
            _set_axes(target, decision, manifest, classified, current_slug, slugify)
            outcome.locked.setdefault(id(target), set()).update(decision.axes)
        outcome.applied += 1

    for slug in [slug for slug, docs in classified.items() if not docs]:
        del classified[slug]  # sin esto, `build()` crearía un `Domain` vacío
    if outcome.stale or outcome.orphan:
        logger.info(f"Decisiones sin aplicar: {len(outcome.stale)} desfasadas, {len(outcome.orphan)} de documentos ausentes")
    return outcome


def _issue(
    decision: ClassificationDecision,
    target: DomainDocument | ConversionResult | None,
    manifest: TaxonomyManifest,
    slugify: Callable[[str], str],
) -> DecisionIssue | None:
    def issue(reason: DecisionIssueReason, detail: str | None = None) -> DecisionIssue:
        return DecisionIssue(decision_id=decision.id, document_key=decision.document_key, reason=reason, detail=detail)

    if target is None or (decision.action != "exclude" and not isinstance(target, DomainDocument)):
        return issue("missing_document", None if target is None else "el documento no tiene conversión")
    if decision.source_sha256 and target.source_sha256 and decision.source_sha256 != target.source_sha256:
        return issue("source_changed")
    for key, values in decision.axes.items():
        axis = manifest.axis(key)
        if axis is None:
            return issue("unknown_axis", key)
        allowed = _allowed(axis, slugify)
        unknown = [value for value in values if _slug(axis, value, slugify) not in allowed]
        if unknown:
            return issue("unknown_value", f"{key}: {', '.join(unknown)}")
        if axis.organizes and len(values) != 1:
            return issue("unknown_value", f"{key}: un eje que organiza lleva exactamente un valor")
    return None


def _allowed(axis: TaxonomyAxis, slugify: Callable[[str], str]) -> set[str]:
    return {_slug(axis, entry.slug, slugify) for entry in axis.entries}


def _slug(axis: TaxonomyAxis, value: str, slugify: Callable[[str], str]) -> str:
    return slugify(value) if axis.organizes else value


def _exclude(
    target: DomainDocument | ConversionResult,
    classified: dict[str, list[DomainDocument]],
    unclassified: list[ConversionResult],
    current_slug: dict[int, str],
) -> None:
    if isinstance(target, DomainDocument):
        slug = current_slug.pop(id(target))
        classified[slug] = [document for document in classified[slug] if document is not target]
    else:
        unclassified.remove(target)


def _set_axes(
    document: DomainDocument,
    decision: ClassificationDecision,
    manifest: TaxonomyManifest,
    classified: dict[str, list[DomainDocument]],
    current_slug: dict[int, str],
    slugify: Callable[[str], str],
) -> None:
    folder, subfolder = manifest.folder_axis, manifest.subfolder_axis
    for key, raw_values in decision.axes.items():
        axis = manifest.axis(key)
        assert axis is not None
        names = {_slug(axis, entry.slug, slugify): entry.name for entry in axis.entries}
        values = [
            AxisValue(slug=slug, name=names[slug], confidence=1.0, classified_by="human")
            for slug in dict.fromkeys(_slug(axis, value, slugify) for value in raw_values)
        ]
        document.classification.axes[key] = values
        if key == folder.key:
            old = current_slug[id(document)]
            new = values[0].slug
            if new != old:
                classified[old] = [candidate for candidate in classified[old] if candidate is not document]
                classified.setdefault(new, []).append(document)
                current_slug[id(document)] = new
            document.confidence = 1.0
        elif key == subfolder.key:
            document.material_type = values[0].slug
            document.material_type_name = values[0].name if values[0].name != values[0].slug else None
            document.material_type_confidence = 1.0
    document.classified_by = "human"


def _revoked(decision: ClassificationDecision, author: str | None, reason: str | None) -> ClassificationDecision:
    return decision.model_copy(update={"revoked_at": datetime.now(UTC).isoformat(timespec="seconds"), "revoked_by": author, "revoke_reason": reason})


def _replace(active: list[ClassificationDecision], new: ClassificationDecision) -> tuple[list[ClassificationDecision], list[ClassificationDecision]]:
    """Las vigentes con `new` añadida, y las que `new` sustituye (al historial como `replaced`)."""

    def replaced(old: ClassificationDecision) -> bool:
        if old.document_key != new.document_key:
            return False
        if new.action in ("confirm", "exclude") or old.action == "exclude":
            return True
        return old.axis == new.axis  # un `confirm` anterior se queda: el `set_axis` se aplica después y gana en su eje

    keep = [decision for decision in active if not replaced(decision)]
    gone = [_revoked(decision, new.author, "replaced") for decision in active if replaced(decision)]
    return [*keep, new], gone


__all__ = [
    "DECISIONS_FILE",
    "ClassificationDecisionStore",
    "DecisionOutcome",
    "apply_decisions",
    "gold_from_decisions",
    "not_applied_without_manifest",
]
