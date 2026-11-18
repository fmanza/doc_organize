"""
Extracto de un documento para la IA (2.0.0, G2): lo que más ayuda a clasificar, en pocos caracteres.

Hasta 1.x el modelo recibía los primeros 4000 caracteres del texto. Muchos documentos empiezan con portadas, índices o
tablas de control de cambios, y lo que dice de qué trata el documento queda fuera. El extracto junta, por este orden y
hasta `MAX_EXCERPT_CHARS`:

1. el título y la carpeta (dos niveles como mucho: la ruta completa puede llevar nombres de personas o clientes);
2. los metadatos que se den (tipo de fichero, autor declarado...);
3. el **esquema de títulos** del documento (los títulos de sección, sin repetir);
4. el **comienzo**: los primeros fragmentos con texto de verdad (se saltan los muy cortos, como «Índice» o «Página 2»);
5. los fragmentos que mencionan **términos del catálogo** (nombres y palabras clave de los valores de los ejes), que no
   estén ya.

Es determinista. Si cambia la forma de construirlo, sube `EXCERPT_VERSION` (forma parte de lo que se envía y, por tanto,
de la clave de la caché).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from doc_organize.utils.folding import FoldedText, fold

if TYPE_CHECKING:  # solo para los tipos: `context` importa `ai` (evita el ciclo)
    from doc_organize.context.conversion_document import ConversionDocument

#: Versión de la forma del extracto: cámbiala si cambia `build_document_excerpt`.
EXCERPT_VERSION = "1"
MAX_EXCERPT_CHARS = 6000
#: Un fragmento con menos letras no cuenta como «texto de verdad» para el comienzo (títulos sueltos, números de página).
_MIN_REAL_TEXT_LETTERS = 40
_MAX_OUTLINE_CHARS = 1500
_MAX_START_CHARS = 2500
_MAX_FRAGMENT_CHARS = 500


def build_document_excerpt(
    document: ConversionDocument,
    *,
    folder: str | None = None,
    metadata: Mapping[str, str | None] | None = None,
    catalog_terms: Iterable[str] = (),
    max_chars: int = MAX_EXCERPT_CHARS,
) -> str:
    """El extracto de `document` para la IA, de `max_chars` caracteres como mucho.

    Args:
        document: El `.json` de conversión leído (`read_conversion_document`).
        folder: Carpeta del original relativa al proyecto; solo se usan sus dos últimos niveles.
        metadata: Datos cortos que se añaden tal cual (`{"Tipo": "pdf", "Autor": "..."}`); los vacíos se omiten.
        catalog_terms: Nombres y palabras clave del catálogo: los fragmentos que los mencionan entran en el extracto.
        max_chars: Tope de caracteres.

    Example:
        >>> from doc_organize.context.conversion_document import ConversionChunk, ConversionDocument
        >>> document = ConversionDocument(title="Plan", chunks=(
        ...     ConversionChunk("Índice"),
        ...     ConversionChunk("Este plan describe la respuesta ante incidentes de seguridad de la información.", ("1. Objeto",)),
        ... ))
        >>> print(build_document_excerpt(document, folder="Seguridad/Planes/2024", catalog_terms=["incidentes"]))
        Título: Plan
        Carpeta: Planes/2024
        Esquema de títulos:
        - 1. Objeto
        Comienzo:
        Este plan describe la respuesta ante incidentes de seguridad de la información.
    """
    lines = [f"Título: {_clean(document.title) or '(sin título)'}"]
    parts = [part for part in (folder or "").replace("\\", "/").split("/") if part and part != "."]
    if parts:
        lines.append(f"Carpeta: {'/'.join(parts[-2:])}")
    lines.extend(f"{key}: {_clean(value)}" for key, value in (metadata or {}).items() if value)

    outline = _outline(document)
    if outline:
        lines.append("Esquema de títulos:")
        lines.extend(f"- {heading}" for heading in outline)

    start, used = _start(document, real_text_only=True)
    if not start:  # ningún fragmento largo (una presentación, un formulario): mejor los cortos que nada
        start, used = _start(document, real_text_only=False)
    if start:
        lines.append("Comienzo:")
        lines.extend(start)

    matches = _catalog_fragments(document, catalog_terms, used)
    if matches:
        lines.append("Fragmentos con términos del catálogo:")
        lines.extend(matches)

    return "\n".join(lines)[:max_chars]


def _catalog_fragments(document: ConversionDocument, catalog_terms: Iterable[str], used: set[int]) -> list[str]:
    """Fragmentos (fuera de `used`) que mencionan algún término del catálogo como palabra o frase completa."""
    terms = sorted({fold(term) for term in catalog_terms if fold(term)})
    if not terms:
        return []
    matches = []
    for index, chunk in enumerate(document.chunks):
        text = _clean(chunk.text)
        if index not in used and text and any(FoldedText.of(text).contains(term) for term in terms):
            matches.append(text[:_MAX_FRAGMENT_CHARS])
    return matches


def _start(document: ConversionDocument, *, real_text_only: bool) -> tuple[list[str], set[int]]:
    """Los primeros fragmentos (solo los de texto de verdad si `real_text_only`) hasta `_MAX_START_CHARS`, y cuáles."""
    start: list[str] = []
    used: set[int] = set()
    size = 0
    for index, chunk in enumerate(document.chunks):
        text = _clean(chunk.text)
        if not text or (real_text_only and sum(char.isalpha() for char in text) < _MIN_REAL_TEXT_LETTERS):
            continue
        start.append(text[: _MAX_START_CHARS - size])
        used.add(index)
        size += len(start[-1])
        if size >= _MAX_START_CHARS:
            break
    return start, used


def _outline(document: ConversionDocument) -> list[str]:
    """Títulos de sección sin repetir, en orden, hasta `_MAX_OUTLINE_CHARS`."""
    seen: set[str] = set()
    outline: list[str] = []
    size = 0
    for chunk in document.chunks:
        for heading in chunk.headings:
            text = _clean(heading)
            if text and text not in seen:
                if size + len(text) > _MAX_OUTLINE_CHARS:
                    return outline
                seen.add(text)
                outline.append(text)
                size += len(text)
    return outline


def _clean(text: str | None) -> str:
    """Una línea, sin caracteres de control (S3: el texto del documento no puede romper la estructura del prompt)."""
    if not text:
        return ""
    return " ".join("".join(char if char.isprintable() else " " for char in text).split())


__all__ = ["EXCERPT_VERSION", "MAX_EXCERPT_CHARS", "build_document_excerpt"]
