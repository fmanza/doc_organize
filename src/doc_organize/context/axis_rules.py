"""
Reglas de los ejes que solo etiquetan (marcos normativos, sistema de gestión...): 2.0.0, A2.

Los ejes organizadores (dominio y tipo de material) siguen con `score_catalog`, para que la reorganización sea la de
1.x. Para los demás, `score_catalog` no sirve (auditoría del plan de facetas, C1-C3):

- busca subcadenas: «ens» encajaba en «ensayos sensibles»;
- divide los aciertos por el número de palabras: añadir palabras clave bajaba la nota;
- los términos que comparten varias entradas («iso», «seguridad») puntuaban en todas.

`AxisRuleScorer` busca **palabras o frases completas** tras plegar acentos y mayúsculas, descarta los términos que
aparecen en dos o más entradas del eje y da la confianza por **términos distintos encontrados**: 1 → 0,6; 2 → 0,8;
3 o más → 1,0.
"""

import re

from collections.abc import Iterable

from doc_organize.core.models import AxisValue, TaxonomyAxis, TaxonomyEntry
from doc_organize.utils.folding import FoldedText, fold

#: Valores como mucho por documento en un eje de varios valores.
MAX_VALUES_PER_AXIS = 5
#: Caracteres del texto (tras el título) en los que buscan las reglas de los ejes que etiquetan. Medido en CALIDAD_VD
#: contra la referencia (marcos normativos): con el texto entero, un documento largo menciona de pasada casi todos los
#: marcos; con el título y el comienzo, F1 de 0,27 a 0,34 (y de 0,43 a 0,50 con palabras clave específicas).
TAG_AXIS_TEXT_CHARS = 6000
#: Confianza según los términos distintos encontrados (1, 2, 3 o más).
_CONFIDENCE_BY_HITS = (0.0, 0.6, 0.8, 1.0)
#: Separadores dentro de un nombre de entrada: «ENS - Esquema Nacional de Seguridad», «LO 3/2018 (LOPDGDD)». La barra
#: no separa: «2016/679» o «ISO/IEC» son una sola cosa.
_NAME_PARTS = re.compile(r"\s[-–—]\s|[(),:;]")
#: Una parte suelta de una sola palabra solo cuenta si es una sigla («ENS», «RGPD», «LOPDGDD»): «Reglamento» o «UE»
#: sueltos encajan en cualquier texto normativo.
_ACRONYM = re.compile(r"^[A-ZÁÉÍÓÚÑ]{3,}$")


class AxisRuleScorer:
    """Clasifica por reglas en un eje que solo etiqueta.

    Términos de cada entrada: el slug como frase (`iso-27001` → «iso 27001»), el slug sin su prefijo compartido con
    otras entradas («27001»), cada palabra clave y el nombre, también partido por sus separadores («ENS - Esquema
    Nacional de Seguridad» → «ens», «esquema nacional de seguridad»). Un término que tienen dos o más entradas del eje
    no cuenta.

    Attributes:
        axis (TaxonomyAxis): Eje que se puntúa.
        threshold (float): Confianza mínima: la del eje o, si no la tiene, la de la construcción.

    Example:
        >>> from doc_organize.core.models import TaxonomyEntry
        >>> axis = TaxonomyAxis(
        ...     key="normative_frameworks", name="Marcos", multiple=True,
        ...     entries=[
        ...         TaxonomyEntry(slug="iso-27001", name="ISO/IEC 27001", keywords=["SGSI", "seguridad"]),
        ...         TaxonomyEntry(slug="ens", name="ENS - Esquema Nacional de Seguridad", keywords=["seguridad"]),
        ...     ],
        ... )
        >>> scorer = AxisRuleScorer(axis, threshold=0.5)
        >>> [(v.slug, v.confidence) for v in scorer.classify(FoldedText.of("SGSI conforme a ISO/IEC 27001 y al ENS"))]
        [('iso-27001', 0.8), ('ens', 0.6)]
        >>> scorer.classify(FoldedText.of("Procedimiento de ensayos sensibles"))
        []
    """

    def __init__(self, axis: TaxonomyAxis, threshold: float) -> None:
        self.axis = axis
        self.threshold = axis.threshold if axis.threshold is not None else threshold
        candidate_terms = [_entry_terms(entry, axis.entries) for entry in axis.entries]
        owners: dict[str, int] = {}
        for terms in candidate_terms:
            for term in terms:
                owners[term] = owners.get(term, 0) + 1
        self._terms = [tuple(sorted(term for term in terms if owners[term] == 1)) for terms in candidate_terms]

    def terms(self, slug: str) -> tuple[str, ...]:
        """Los términos discriminantes de la entrada `slug` (para explicar o depurar un catálogo)."""
        for entry, terms in zip(self.axis.entries, self._terms, strict=True):
            if entry.slug == slug:
                return terms
        return ()

    def classify(self, text: FoldedText) -> list[AxisValue]:
        """Valores del eje para `text`: los que llegan al umbral, de mayor a menor confianza (en empate, el orden del
        catálogo); como mucho 5 si el eje es de varios valores y solo el mejor si no. Vacío si el eje es `rules: false`.
        """
        if not self.axis.rules:
            return []
        scored = []
        for entry, terms in zip(self.axis.entries, self._terms, strict=True):
            hits = sum(1 for term in terms if text.contains(term))
            confidence = _CONFIDENCE_BY_HITS[min(hits, len(_CONFIDENCE_BY_HITS) - 1)]
            if hits and confidence >= self.threshold:
                scored.append(AxisValue(slug=entry.slug, name=entry.name, confidence=confidence, classified_by="rules"))
        scored.sort(key=lambda value: value.confidence, reverse=True)  # estable: en empate, el orden del catálogo
        return scored[:MAX_VALUES_PER_AXIS] if self.axis.multiple else scored[:1]


def _entry_terms(entry: TaxonomyEntry, siblings: Iterable[TaxonomyEntry]) -> set[str]:
    slug_words = fold(entry.slug).split()
    terms = {" ".join(slug_words), fold(entry.name)}
    terms.update(fold(part) for part in _NAME_PARTS.split(entry.name) if _is_name_term(part))
    terms.update(fold(keyword) for keyword in entry.keywords)
    shared_heads = {fold(other.slug).split()[0] for other in siblings if other is not entry and fold(other.slug)}
    if len(slug_words) > 1 and slug_words[0] in shared_heads:
        terms.add(" ".join(slug_words[1:]))  # «iso-27001» → «27001» si otra entrada empieza por «iso»
    return {term for term in terms if term}


def _is_name_term(part: str) -> bool:
    """Una parte del nombre cuenta si tiene dos o más palabras o si es una sigla."""
    words = fold(part).split()
    return len(words) >= 2 or (len(words) == 1 and bool(_ACRONYM.match(part.strip())))


__all__ = ["MAX_VALUES_PER_AXIS", "TAG_AXIS_TEXT_CHARS", "AxisRuleScorer", "FoldedText", "fold"]
