"""Saneado de textos cortos de metadatos (descripción, palabras clave) que vienen de documentos o de la IA (1.5.0)."""

import re

MAX_TEXT_LENGTH = 500
MAX_KEYWORDS = 20
MAX_KEYWORD_LENGTH = 60


def clean_text(value: object, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    """Texto en una línea, sin espacios sobrantes y recortado a `max_length`; `None` si no es texto o queda vacío.

    Example:
        >>> clean_text("  Informe\\n anual ")
        'Informe anual'
        >>> clean_text("   ") is None
        True
    """
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:max_length] or None


def clean_keywords(values: object, limit: int = MAX_KEYWORDS) -> list[str]:
    """Palabras clave limpias y sin repetir (sin distinguir mayúsculas), hasta `limit`.

    Acepta una cadena separada por comas o punto y coma (como la guardan PDF y Office) o una lista de cadenas; lo que
    no es texto se descarta.

    Example:
        >>> clean_keywords("calidad; ISO 9001, Calidad,,")
        ['calidad', 'ISO 9001']
    """
    if isinstance(values, str):
        candidates: list[object] = list(re.split(r"[,;]", values))
    elif isinstance(values, list):
        candidates = values
    else:
        return []
    keywords: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        keyword = clean_text(candidate, MAX_KEYWORD_LENGTH)
        if keyword is None or keyword.casefold() in seen:
            continue
        seen.add(keyword.casefold())
        keywords.append(keyword)
    return keywords[:limit]


__all__ = ["MAX_KEYWORDS", "MAX_KEYWORD_LENGTH", "MAX_TEXT_LENGTH", "clean_keywords", "clean_text"]
