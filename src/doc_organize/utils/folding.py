"""
Plegado de texto para buscar palabras y frases completas sin distinguir mayúsculas ni acentos (2.0.0).

Lo usan las reglas de los ejes (`context.axis_rules`), el extracto del documento y la comprobación de las citas de la IA
(`ai`). Vive aquí, sin dependencias, para que `ai` y `context` puedan usarlo sin importarse entre sí.
"""

import re
import unicodedata

from dataclasses import dataclass

_NON_WORD = re.compile(r"[^0-9a-z]+")


def fold(text: str) -> str:
    """Minúsculas, sin acentos y con todo lo que no es letra o dígito como un espacio: `«ISO/IEC 27001»` → `iso iec 27001`.

    Example:
        >>> fold("Administración Pública: ISO/IEC 27001")
        'administracion publica iso iec 27001'
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_WORD.sub(" ", without_marks).strip()


@dataclass(frozen=True)
class FoldedText:
    """El texto de un documento preparado para buscar términos completos: plegado una vez, con sus palabras."""

    padded: str
    words: frozenset[str]

    @classmethod
    def of(cls, *parts: str | None) -> "FoldedText":
        """Pliega y une `parts` (título, texto...) separados por un espacio."""
        folded = fold(" ".join(part for part in parts if part))
        return cls(padded=f" {folded} ", words=frozenset(folded.split()))

    def contains(self, term: str) -> bool:
        """`True` si `term` (ya plegado) aparece como palabra o frase completa."""
        words = term.split()
        if not all(word in self.words for word in words):  # descarte barato antes de buscar la frase
            return False
        return len(words) == 1 or f" {term} " in self.padded


__all__ = ["FoldedText", "fold"]
