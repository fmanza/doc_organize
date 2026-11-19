"""
Sub-fase semántica (2.0.0, G4, opt-in por D13): rellenar ejes vacíos comparando embeddings, sin llamar al modelo de
lenguaje.

Va después de las reglas y las decisiones y antes de la IA (`ContextBuilder.build(semantic=True)`). Para cada
documento con algún eje vacío (y no decidido por una persona) compara el vector de su extracto con el de cada valor del
catálogo («nombre. descripción. palabras clave»):

- en un eje de un valor, asigna el más parecido si la similitud llega al umbral **y** le saca `SEMANTIC_MARGIN` al
  segundo (si dos valores empatan, mejor dejarlo a la IA o a una persona);
- en un eje de varios valores, todos los que llegan al umbral, hasta 5.

Lo asignado queda con `classified_by="semantic"` y la similitud como confianza; la IA solo ve lo que siga vacío.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from doc_organize.ai.embeddings import EmbeddingIndex, cosine
from doc_organize.ai.excerpt import build_document_excerpt
from doc_organize.ai.llm_client import LlmClient
from doc_organize.ai.services import MAX_CONTENT_CHARS, MAX_VALUES_PER_AXIS
from doc_organize.context.conversion_document import read_conversion_document
from doc_organize.core.constants import UNCLASSIFIED_SLUG
from doc_organize.core.exceptions import AiError
from doc_organize.core.models import AiPhaseStats, AxisValue, DomainDocument, TaxonomyAxis, TaxonomyEntry, TaxonomyManifest
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

#: Similitud mínima por defecto para asignar un valor.
DEFAULT_SEMANTIC_THRESHOLD = 0.75
#: Ventaja mínima del mejor valor sobre el segundo en un eje de un valor.
SEMANTIC_MARGIN = 0.03
#: Ejemplos de documentos parecidos que recibe la IA por documento (G4).
DEFAULT_AI_EXAMPLES = 3
#: Confianza mínima en un eje que organiza para que un documento sirva de ejemplo (si no lo decidió una persona).
EXAMPLE_MIN_CONFIDENCE = 0.9
#: Un eje con más valores que esto se preselecciona: al modelo solo van los `PRESELECT_TOP` más parecidos.
PRESELECT_MIN_ENTRIES = 25
PRESELECT_TOP = 15


def entry_text(axis: TaxonomyAxis, entry: TaxonomyEntry) -> str:
    """El texto de un valor del catálogo que se compara con los documentos.

    Example:
        >>> entry_text(TaxonomyAxis(key="d", name="Dominios", entries=[TaxonomyEntry(slug="c", name="C")]),
        ...            TaxonomyEntry(slug="calidad", name="Calidad", description="Sistema de gestión", keywords=["ISO 9001"]))
        'Dominios: Calidad. Sistema de gestión. ISO 9001'
    """
    parts = [f"{axis.name}: {entry.name}", entry.description or "", ", ".join(entry.keywords)]
    return ". ".join(part for part in parts if part)


def best_values(document: list[float], entries: list[tuple[str, list[float]]], *, multiple: bool, threshold: float) -> list[tuple[str, float]]:
    """Los valores que se asignan a un eje: `(slug, similitud)`, del más parecido al menos.

    Example:
        >>> best_values([1.0, 0.0], [("a", [1.0, 0.0]), ("b", [0.0, 1.0])], multiple=False, threshold=0.75)
        [('a', 1.0)]
    """
    scored = sorted(((slug, cosine(document, vector)) for slug, vector in entries), key=lambda item: item[1], reverse=True)
    if multiple:
        return [(slug, round(score, 4)) for slug, score in scored if score >= threshold][:MAX_VALUES_PER_AXIS]
    if not scored or scored[0][1] < threshold:
        return []
    if len(scored) > 1 and scored[0][1] - scored[1][1] < SEMANTIC_MARGIN:
        return []  # empate: mejor no decidir
    return [(scored[0][0], round(scored[0][1], 4))]


async def classify_semantic(
    llm: LlmClient,
    classified: dict[str, list[DomainDocument]],
    manifest: TaxonomyManifest,
    *,
    project_root: str | Path,
    threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    locked: dict[int, set[str]] | None = None,
    slugify: Callable[[str], str] = str,
) -> AiPhaseStats:
    """Rellena con embeddings los ejes vacíos de `classified` (in-place, moviendo de dominio si hace falta).

    Un fallo del modelo de embeddings no para la construcción: se registra y la fase queda sin asignar nada
    (`AiPhaseStats.failed`).
    """
    stats = AiPhaseStats()
    pending = [
        (slug, document, keys)
        for slug, documents in classified.items()
        for document in documents
        if (keys := _missing(slug, document, manifest, (locked or {}).get(id(document), set())))
    ]
    if not pending:
        return stats
    index = EmbeddingIndex(project_root, model=llm.model_for("embed"), redacted=llm.settings.redact_credentials)
    axes = {axis.key: axis for axis in manifest.axes}
    wanted = sorted({key for _, _, keys in pending for key in keys})
    catalog = [(key, _slug(axes[key], entry, slugify), entry_text(axes[key], entry)) for key in wanted for entry in axes[key].entries]
    readable = [(item, excerpt) for item in pending if (excerpt := await _excerpt(item[1]))]
    if not readable:
        return stats
    try:
        vectors = await index.vectors(llm, [text for _, _, text in catalog] + [excerpt for _, excerpt in readable])
    except AiError as exc:
        logger.warning(f"Falló la clasificación semántica: {exc}")
        stats.failed = len(pending)
        return stats
    entry_vectors: dict[str, list[tuple[str, list[float]]]] = {}
    for (key, slug, _), vector in zip(catalog, vectors, strict=False):
        entry_vectors.setdefault(key, []).append((slug, vector))
    for ((old_slug, document, keys), _), vector in zip(readable, vectors[len(catalog) :], strict=True):
        values = {key: best_values(vector, entry_vectors[key], multiple=axes[key].multiple, threshold=threshold) for key in keys}
        if _apply(document, old_slug, values, classified, manifest, slugify):
            stats.assigned += 1
    stats.sent, stats.cached = index.embedded, index.reused
    for slug in [slug for slug, documents in classified.items() if not documents]:
        del classified[slug]
    return stats


@dataclass
class AiHints:
    """Lo que la sub-fase semántica le pasa a la IA para un documento (2.0.0, G4).

    Attributes:
        examples (list[str]): Documentos parecidos ya clasificados con fiabilidad, una línea cada uno.
        preselected (dict[str, list[str]]): Por eje con más de `PRESELECT_MIN_ENTRIES` valores, los
            `PRESELECT_TOP` más parecidos al documento: solo esos van al modelo.
    """

    examples: list[str] = field(default_factory=list)
    preselected: dict[str, list[str]] = field(default_factory=dict)


async def ai_hints(
    llm: LlmClient,
    classified: dict[str, list[DomainDocument]],
    manifest: TaxonomyManifest,
    pending: Sequence[tuple[DomainDocument, list[str]]],
    *,
    project_root: str | Path,
    examples: int = DEFAULT_AI_EXAMPLES,
    exclude: Iterable[str] = (),
    slugify: Callable[[str], str] = str,
) -> dict[int, AiHints]:
    """Ejemplos y preselección para los documentos que van a la IA (`pending`: documento y ejes que se le piden),
    por `id()` del documento.

    Los ejemplos salen de los documentos clasificados **con fiabilidad** (un valor de una persona, o confianza de al
    menos `EXAMPLE_MIN_CONFIDENCE` en un eje que organiza), los `examples` más parecidos. **Nunca** son el propio
    documento, sus duplicados (mismo `source_sha256`) ni los de `exclude` (al evaluar, los de la referencia: si no, el
    modelo vería la respuesta, B16). Un fallo del modelo de embeddings deja la IA sin ayudas, sin parar nada.
    """
    if not pending:
        return {}
    index = EmbeddingIndex(project_root, model=llm.model_for("embed"), redacted=llm.settings.redact_credentials)
    excluded = set(exclude)
    documents = [document for docs in classified.values() for document in docs]
    trusted = [document for document in documents if _trusted(document, manifest) and document.source_path not in excluded]
    wanted = {id(document) for document, _ in pending} | {id(document) for document in trusted}
    readable = [(document, excerpt) for document in documents if id(document) in wanted and (excerpt := await _excerpt(document))]
    big = [axis for axis in manifest.axes if len(axis.entries) > PRESELECT_MIN_ENTRIES]
    catalog = [(axis, entry) for axis in big for entry in axis.entries]
    try:
        vectors = await index.vectors(llm, [entry_text(axis, entry) for axis, entry in catalog] + [excerpt for _, excerpt in readable])
    except AiError as exc:
        logger.warning(f"Sin ejemplos ni preselección para la IA: falló el modelo de embeddings: {exc}")
        return {}
    by_document = {id(document): vector for (document, _), vector in zip(readable, vectors[len(catalog) :], strict=True)}
    entry_vectors: dict[str, list[tuple[str, list[float]]]] = {}
    for (axis, entry), vector in zip(catalog, vectors, strict=False):
        entry_vectors.setdefault(axis.key, []).append((_slug(axis, entry, slugify), vector))
    pool = [(document, by_document[id(document)]) for document in trusted if id(document) in by_document]
    hints = {}
    for document, keys in pending:
        own = by_document.get(id(document))
        if own is None:
            continue
        neighbours = sorted(
            ((other, cosine(own, other_vector)) for other, other_vector in pool if not _same_document(document, other)),
            key=lambda item: item[1],
            reverse=True,
        )
        lines = [line for other, _ in neighbours if (line := _example_line(other, keys))][:examples]
        preselected = {
            key: [slug for slug, _ in sorted(entry_vectors[key], key=lambda item: cosine(own, item[1]), reverse=True)[:PRESELECT_TOP]]
            for key in keys
            if key in entry_vectors
        }
        hints[id(document)] = AiHints(examples=lines, preselected=preselected)
    return hints


def _trusted(document: DomainDocument, manifest: TaxonomyManifest) -> bool:
    values = [value for values in document.classification.axes.values() for value in values]
    if any(value.classified_by == "human" for value in values):
        return True
    organizers = (manifest.folder_axis.key, manifest.subfolder_axis.key)
    return any(value.confidence >= EXAMPLE_MIN_CONFIDENCE for key in organizers for value in document.classification.axes.get(key, []))


def _same_document(document: DomainDocument, other: DomainDocument) -> bool:
    """El propio documento o un duplicado suyo (mismo original): nunca puede ser su ejemplo."""
    if other is document or other.source_path == document.source_path:
        return True
    return bool(document.source_sha256) and document.source_sha256 == other.source_sha256


def _example_line(document: DomainDocument, keys: list[str]) -> str:
    """`«Título» → eje: valor, valor; eje: valor` con los ejes pedidos que tiene el ejemplo; vacío si no tiene ninguno."""
    parts = [f"{key}: {', '.join(value.slug for value in values)}" for key in keys if (values := document.classification.axes.get(key))]
    return f"«{document.title}» → {'; '.join(parts)}" if parts else ""


def _missing(domain_slug: str, document: DomainDocument, manifest: TaxonomyManifest, decided: set[str]) -> list[str]:
    keys = []
    if domain_slug == UNCLASSIFIED_SLUG:
        keys.append(manifest.folder_axis.key)
    if document.material_type == UNCLASSIFIED_SLUG:
        keys.append(manifest.subfolder_axis.key)
    keys += [axis.key for axis in manifest.tag_axes if not document.classification.axes.get(axis.key)]
    return [key for key in keys if key not in decided]


def _slug(axis: TaxonomyAxis, entry: TaxonomyEntry, slugify: Callable[[str], str]) -> str:
    return slugify(entry.slug) if axis.organizes else entry.slug


async def _excerpt(document: DomainDocument) -> str | None:
    conversion = await read_conversion_document(document.json_path) if document.json_path else None
    if conversion is None:
        return None
    return build_document_excerpt(conversion, folder=str(Path(document.source_path).parent), max_chars=MAX_CONTENT_CHARS)


def _apply(
    document: DomainDocument,
    old_slug: str,
    values: dict[str, list[tuple[str, float]]],
    classified: dict[str, list[DomainDocument]],
    manifest: TaxonomyManifest,
    slugify: Callable[[str], str],
) -> bool:
    changed = False
    for key, chosen in values.items():
        if not chosen:
            continue
        axis = manifest.axis(key)
        assert axis is not None
        names = {_slug(axis, entry, slugify): entry.name for entry in axis.entries}
        axis_values = [AxisValue(slug=slug, name=names.get(slug, slug), confidence=score, classified_by="semantic") for slug, score in chosen]
        document.classification.axes[key] = axis_values
        if key == manifest.folder_axis.key:
            classified[old_slug] = [candidate for candidate in classified[old_slug] if candidate is not document]
            classified.setdefault(axis_values[0].slug, []).append(document)
            document.confidence = axis_values[0].confidence
        elif key == manifest.subfolder_axis.key:
            document.material_type = axis_values[0].slug
            document.material_type_name = axis_values[0].name if axis_values[0].name != axis_values[0].slug else None
            document.material_type_confidence = axis_values[0].confidence
        changed = True
    if changed and document.classified_by == "rules":
        document.classified_by = "semantic"
    return changed


__all__ = [
    "DEFAULT_AI_EXAMPLES",
    "DEFAULT_SEMANTIC_THRESHOLD",
    "EXAMPLE_MIN_CONFIDENCE",
    "PRESELECT_MIN_ENTRIES",
    "PRESELECT_TOP",
    "SEMANTIC_MARGIN",
    "AiHints",
    "ai_hints",
    "best_values",
    "classify_semantic",
    "entry_text",
]
