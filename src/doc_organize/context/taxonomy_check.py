"""
Comprobación de un manifiesto por reglas, sin IA (2.0.0, G5): cuánto cubre cada eje y dónde duda.

`check_taxonomy_rules` clasifica los documentos con un manifiesto **candidato** igual que la fase de reglas de
`ContextBuilder.build` (mismos puntuadores, mismo umbral y mismo texto), pero sin guardar nada, sin IA y sin
reorganizar: es lo que usa el agente diseñador para probar sus propuestas y lo que mide si una propuesta mejora la
plantilla de partida (puerta de M8).

Por eje:

- **Cobertura**: fracción de documentos con algún valor por reglas.
- **Conflictos** (ejes de un valor): documentos en los que dos o más entradas llegan al umbral y las dos mejores quedan
  a menos de `CONFLICT_MARGIN`; las reglas eligen la primera del catálogo, casi por azar.
- **Entradas vacías**: valores que no recibe ningún documento.
- **Términos compartidos**: palabras clave que tienen dos o más entradas del eje (en los ejes que etiquetan, las reglas
  las descartan; en los que organizan, suman a las dos).

Los textos se leen una vez (`RulesCorpus.load`) y cada comprobación es solo cálculo, para probar muchas variantes.

Example:
    ```python
    corpus = await RulesCorpus.load(documents)
    base = check_taxonomy_rules(manifest, corpus)
    nuevo = check_taxonomy_rules(propuesta, corpus)
    print(base.to_markdown(), nuevo.to_markdown(), nuevo.improves_on(base))
    ```
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from doc_organize.context.axis_rules import TAG_AXIS_TEXT_CHARS, AxisRuleScorer
from doc_organize.context.domain_classifier import _DEFAULT_THRESHOLD, DomainClassifier, MaterialTypeClassifier, fold_accents, read_conversion_json
from doc_organize.context.evaluation import common_root, document_keys
from doc_organize.core.models import ConversionResult, TaxonomyAxis, TaxonomyManifest
from doc_organize.utils.folding import FoldedText, fold

Scorer = Callable[["CorpusDocument"], list[tuple[str, float]]]

#: Diferencia de puntuación entre las dos mejores entradas por debajo de la cual un documento cuenta como conflicto.
CONFLICT_MARGIN = 0.1
#: Ejemplos de documentos sin cubrir y en conflicto que trae cada eje del informe.
REPORT_EXAMPLES = 10


@dataclass
class CorpusDocument:
    """Un documento leído para las reglas."""

    document: ConversionResult
    key: str
    title: str | None
    chunks_text: str

    @cached_property
    def haystack(self) -> str:
        """Título y texto plegados, como los compara `score_catalog` (subcadenas)."""
        return fold_accents(f"{self.title or ''} {self.chunks_text}".lower())

    @cached_property
    def tag_text(self) -> FoldedText:
        """Título y comienzo del texto, como los compara `AxisRuleScorer` (palabras completas)."""
        return FoldedText.of(self.title, self.chunks_text[:TAG_AXIS_TEXT_CHARS])

    @property
    def folder(self) -> str:
        """Carpeta relativa a la raíz (vacío en la raíz)."""
        parent = str(PurePosixPath(self.key).parent)
        return "" if parent == "." else parent

    @property
    def display_title(self) -> str:
        return self.title or PurePosixPath(self.key).stem


@dataclass
class RulesCorpus:
    """Los documentos con su texto ya leído (una sola lectura para muchas comprobaciones).

    Attributes:
        documents (list[CorpusDocument]): Los que se pudieron leer, en el orden dado.
        unreadable (list[str]): Claves de los que no (sin `.json` o no válido): no cuentan en la cobertura.
    """

    documents: list[CorpusDocument] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @classmethod
    async def load(cls, documents: Sequence[ConversionResult], *, roots: Sequence[str] | None = None) -> RulesCorpus:
        """Lee el `.json` de cada documento convertido; las claves son rutas relativas a `roots` (por defecto, la
        carpeta común de todos)."""
        paths = [document.source_path for document in documents]
        if roots is None:
            root = common_root(paths)
            roots = [root] if root else []
        keys = document_keys(paths, roots)
        corpus = cls()
        for document in documents:
            read = await read_conversion_json(document.json_path) if document.success and document.json_path else None
            if read is None:
                corpus.unreadable.append(keys[document.source_path])
                continue
            chunks_text, title = read
            corpus.documents.append(CorpusDocument(document=document, key=keys[document.source_path], title=title, chunks_text=chunks_text))
        return corpus


class NearMiss(BaseModel):
    """La entrada que más se acercó al umbral en un documento sin valor.

    Attributes:
        slug (str): Entrada.
        score (float): Su puntuación (por debajo del umbral).
        matched (list[str]): Términos de la entrada que aparecen en el documento.
        missing (list[str]): Los que no: en un eje que organiza, quitarlos (o cambiarlos por otros que aparezcan) sube
            la puntuación.
    """

    slug: str
    score: float
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class AxisRulesReport(BaseModel):
    """Cómo clasifican las reglas un eje.

    Attributes:
        axis (str): Clave del eje.
        organizes (str | None): `folder`, `subfolder` o `None` (solo etiqueta).
        documents (int): Documentos comprobados.
        covered (int): Documentos con algún valor.
        conflicts (int): Documentos en conflicto (solo ejes de un valor).
        entry_counts (dict[str, int]): Documentos por valor (el mejor en los ejes de un valor; todos en los de varios).
        empty_entries (list[str]): Valores sin ningún documento.
        shared_terms (dict[str, list[str]]): Término compartido → entradas que lo tienen.
        unused_keywords (dict[str, list[str]]): Entrada → palabras clave que no aparecen en ningún documento (en los
            ejes que organizan, además, bajan la puntuación de la entrada).
        uncovered_examples (list[str]): Algunos documentos sin valor (clave).
        conflict_examples (dict[str, list[str]]): Algunos documentos en conflicto → entradas empatadas.
        conflict_terms (dict[str, dict[str, list[str]]]): De esos documentos, los términos que encajan en cada entrada
            empatada (lo que hay que cambiar para desempatar).
        near_misses (dict[str, NearMiss]): De los documentos sin valor de un eje que organiza, la entrada que más se
            acercó al umbral, con los términos que encajan y los que faltan.
    """

    axis: str
    organizes: str | None = None
    documents: int = 0
    covered: int = 0
    conflicts: int = 0
    entry_counts: dict[str, int] = Field(default_factory=dict)
    empty_entries: list[str] = Field(default_factory=list)
    shared_terms: dict[str, list[str]] = Field(default_factory=dict)
    unused_keywords: dict[str, list[str]] = Field(default_factory=dict)
    uncovered_examples: list[str] = Field(default_factory=list)
    conflict_examples: dict[str, list[str]] = Field(default_factory=dict)
    conflict_terms: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    near_misses: dict[str, NearMiss] = Field(default_factory=dict)

    @property
    def coverage(self) -> float:
        """Fracción de documentos con algún valor (0 si no hay documentos)."""
        return self.covered / self.documents if self.documents else 0.0


class TaxonomyRulesReport(BaseModel):
    """Resultado de `check_taxonomy_rules`: un informe por eje, en el orden del manifiesto."""

    axes: list[AxisRulesReport] = Field(default_factory=list)
    documents: int = 0
    unreadable: int = 0

    def axis(self, key: str) -> AxisRulesReport | None:
        return next((axis for axis in self.axes if axis.axis == key), None)

    def improves_on(self, base: TaxonomyRulesReport) -> bool:
        """Si este informe mejora `base` (puerta de M8): en todos los ejes que tienen los dos, la cobertura no baja y los
        conflictos no suben, y en alguno la cobertura sube o los conflictos bajan.

        Example:
            >>> base = TaxonomyRulesReport(axes=[AxisRulesReport(axis="domains", documents=10, covered=6, conflicts=3)])
            >>> new = TaxonomyRulesReport(axes=[AxisRulesReport(axis="domains", documents=10, covered=8, conflicts=1)])
            >>> new.improves_on(base) == True and base.improves_on(new) == False
            True
        """
        better = False
        for axis in self.axes:
            before = base.axis(axis.axis)
            if before is None:
                continue
            if axis.covered < before.covered or axis.conflicts > before.conflicts:
                return False
            better = better or axis.covered > before.covered or axis.conflicts < before.conflicts
        return better

    def to_markdown(self) -> str:
        """Tabla por eje.

        Example:
            >>> print(TaxonomyRulesReport(axes=[AxisRulesReport(axis="domains", documents=4, covered=3, conflicts=1)]).to_markdown())
            | Eje | Documentos | Cobertura | Conflictos | Entradas vacías |
            |---|---|---|---|---|
            | domains | 4 | 75,0 % | 1 | 0 |
        """
        lines = ["| Eje | Documentos | Cobertura | Conflictos | Entradas vacías |", "|---|---|---|---|---|"]
        for axis in self.axes:
            coverage = f"{axis.coverage * 100:.1f} %".replace(".", ",")
            lines.append(f"| {axis.axis} | {axis.documents} | {coverage} | {axis.conflicts} | {len(axis.empty_entries)} |")
        return "\n".join(lines)


def check_taxonomy_rules(manifest: TaxonomyManifest, corpus: RulesCorpus, *, threshold: float = _DEFAULT_THRESHOLD) -> TaxonomyRulesReport:
    """Clasifica `corpus` por reglas con `manifest` (como `ContextBuilder.build` sin IA) y mide cada eje.

    Args:
        manifest: Manifiesto candidato (no se guarda).
        corpus: Documentos ya leídos (`RulesCorpus.load`).
        threshold: Umbral de la construcción (el de `build`, por defecto).
    """
    return TaxonomyRulesReport(
        axes=[_check_axis(manifest, axis, corpus, threshold) for axis in manifest.axes],
        documents=len(corpus.documents),
        unreadable=len(corpus.unreadable),
    )


def _check_axis(manifest: TaxonomyManifest, axis: TaxonomyAxis, corpus: RulesCorpus, threshold: float) -> AxisRulesReport:
    report = AxisRulesReport(axis=axis.key, organizes=axis.organizes, documents=len(corpus.documents))
    score = _scorer(axis, threshold)
    terms = _terms_by_entry(axis, threshold)
    counts: Counter[str] = Counter()
    for item in corpus.documents:
        scores = score(item)  # (slug, puntuación) de cada entrada, en el orden del catálogo
        ranked = _ranked(scores, threshold)
        if not ranked:
            if len(report.uncovered_examples) < REPORT_EXAMPLES:
                report.uncovered_examples.append(item.key)
                near = max(scores, key=lambda pair: pair[1], default=None)
                if near is not None and near[1] > 0 and axis.organizes is not None:
                    matched, missing = _split_terms(axis, terms[near[0]], item)
                    report.near_misses[item.key] = NearMiss(slug=near[0], score=round(near[1], 3), matched=matched, missing=missing)
            continue
        report.covered += 1
        counts.update(slug for slug, _ in (ranked if axis.multiple else ranked[:1]))
        if not axis.multiple and len(ranked) > 1 and ranked[0][1] - ranked[1][1] < CONFLICT_MARGIN:
            report.conflicts += 1
            if len(report.conflict_examples) < REPORT_EXAMPLES:
                tied = [slug for slug, value in ranked if ranked[0][1] - value < CONFLICT_MARGIN]
                report.conflict_examples[item.key] = tied
                report.conflict_terms[item.key] = {slug: _split_terms(axis, terms[slug], item)[0] for slug in tied}
    slugs = _slugs(axis)
    report.entry_counts = {slug: counts.get(slug, 0) for slug in slugs}
    report.empty_entries = [slug for slug in slugs if not counts.get(slug)]
    report.shared_terms = _shared_terms(axis)
    report.unused_keywords = _unused_keywords(axis, corpus)
    return report


def _scorer(axis: TaxonomyAxis, threshold: float) -> Scorer:
    """Función documento → `[(slug, puntuación)]` de cada entrada, con los puntuadores de `build`. En los ejes que
    organizan, todas las entradas; en los que etiquetan, las que llegan al umbral."""
    keywords = {DomainClassifier._slugify(entry.slug): entry.keywords for entry in axis.entries if entry.keywords}
    if axis.organizes == "folder":
        domains = DomainClassifier(candidate_domains=[entry.slug for entry in axis.entries], threshold=threshold)
        return lambda item: domains.score_candidates(item.document, item.chunks_text, item.title, extra_keywords=keywords)
    if axis.organizes == "subfolder":
        materials = MaterialTypeClassifier([entry.slug for entry in axis.entries], threshold=threshold)
        return lambda item: materials.score_candidates(title=item.title, chunks_text=item.chunks_text, extra_keywords=keywords)
    tags = AxisRuleScorer(axis, threshold)
    return lambda item: [(value.slug, value.confidence) for value in tags.scores(item.tag_text)]


def _terms_by_entry(axis: TaxonomyAxis, threshold: float) -> dict[str, list[str]]:
    """Los términos con los que puntúan las reglas cada entrada (por el slug con el que aparece en el informe)."""
    if axis.organizes is None:
        scorer = AxisRuleScorer(axis, threshold)
        return {entry.slug: list(scorer.terms(entry.slug)) for entry in axis.entries}
    terms = {}
    for entry in axis.entries:
        slug = DomainClassifier._slugify(entry.slug)
        terms[slug] = [fold_accents(term) for term in [*slug.replace("-", " ").split(), *entry.keywords] if term]
    return terms


def _split_terms(axis: TaxonomyAxis, terms: list[str], item: CorpusDocument) -> tuple[list[str], list[str]]:
    """Los términos que aparecen en el documento y los que no, con el criterio de las reglas del eje."""
    found = [term for term in terms if (item.tag_text.contains(term) if axis.organizes is None else term in item.haystack)]
    return found, [term for term in terms if term not in found]


def _ranked(scores: list[tuple[str, float]], threshold: float) -> list[tuple[str, float]]:
    """Las que tienen algún acierto y llegan al umbral, de mayor a menor; en empate, el orden del catálogo (como
    `score_catalog`)."""
    kept = [(slug, value) for slug, value in scores if value > 0 and value >= threshold]
    return sorted(kept, key=lambda item: item[1], reverse=True)


def _slugs(axis: TaxonomyAxis) -> list[str]:
    if axis.organizes is None:
        return [entry.slug for entry in axis.entries]
    return [DomainClassifier._slugify(entry.slug) for entry in axis.entries]


def _unused_keywords(axis: TaxonomyAxis, corpus: RulesCorpus) -> dict[str, list[str]]:
    """Palabras clave de cada entrada que no aparecen en ningún documento, con el criterio de las reglas del eje."""
    unused: dict[str, list[str]] = {}
    for entry in axis.entries:
        for keyword in entry.keywords:
            if axis.organizes is None:
                term = fold(keyword)
                found = bool(term) and any(item.tag_text.contains(term) for item in corpus.documents)
            else:
                term = fold_accents(keyword)
                found = bool(term) and any(term in item.haystack for item in corpus.documents)
            if not found:
                unused.setdefault(entry.slug, []).append(keyword)
    return unused


def _shared_terms(axis: TaxonomyAxis) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for entry in axis.entries:
        terms = {fold(keyword) for keyword in entry.keywords} | {fold(entry.slug)}
        for term in terms:
            if term:
                owners.setdefault(term, []).append(entry.slug)
    return {term: slugs for term, slugs in sorted(owners.items()) if len(slugs) > 1}


__all__ = [
    "CONFLICT_MARGIN",
    "AxisRulesReport",
    "CorpusDocument",
    "NearMiss",
    "RulesCorpus",
    "TaxonomyRulesReport",
    "check_taxonomy_rules",
]
