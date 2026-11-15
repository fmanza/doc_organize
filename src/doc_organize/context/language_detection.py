"""Idioma principal de un documento a partir de su texto convertido, con py3langid (1.5.0).

py3langid (langid.py) es local, determinista y cubre 97 idiomas. Con textos cortos se equivoca con confianza baja
("Política de calidad" sale gallego al 33 %), así que un resultado solo se acepta con texto suficiente y confianza alta;
si no, el idioma queda sin determinar (`None`) en lugar de adivinarse.
"""

from functools import cache
from typing import Any

#: Letras mínimas en la muestra para intentar la detección.
MIN_LETTERS = 40
#: Probabilidad mínima (normalizada, 0-1) para aceptar el idioma detectado.
MIN_CONFIDENCE = 0.7
_SAMPLE_CHARS = 4000
#: Etiqueta de py3langid para «sin contenido lingüístico».
_NO_LANGUAGE = "zxx"


@cache
def _identifier() -> Any:
    # Carga diferida (~0,4 s la primera vez): solo si se llega a detectar algo.
    from py3langid.langid import MODEL_FILE, LanguageIdentifier

    return LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)


def detect_language(text: str) -> str | None:
    """Código ISO 639-1 del idioma de `text` (p. ej. `'es'`, `'en'`), o `None` si no se puede determinar con seguridad.

    Se analizan los primeros 4000 caracteres. `None` si tienen menos de `MIN_LETTERS` letras, si la probabilidad no
    llega a `MIN_CONFIDENCE` o si no hay contenido lingüístico.

    Example:
        >>> detect_language("Procedimiento de auditoría interna del sistema de gestión de calidad conforme a ISO 9001.")
        'es'
        >>> detect_language("ISO 9001") is None
        True
    """
    sample = text[:_SAMPLE_CHARS]
    if sum(character.isalpha() for character in sample) < MIN_LETTERS:
        return None
    language, probability = _identifier().classify(sample)
    if language == _NO_LANGUAGE or float(probability) < MIN_CONFIDENCE:
        return None
    return str(language)


__all__ = ["MIN_CONFIDENCE", "MIN_LETTERS", "detect_language"]
