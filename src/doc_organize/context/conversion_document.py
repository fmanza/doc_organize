"""
El `.json` de conversión de un documento, completo (2.0.0, G2): título, fragmentos con su ruta de títulos y la huella
del original.

`read_conversion_json` (1.x) devuelve solo el texto unido y el título: es lo que necesitan las reglas. El extracto que se
envía a la IA (`build_document_excerpt`) necesita además los títulos de sección de cada fragmento (`headings`, que el
conversor guarda y hasta 1.7 se descartaban).
"""

import asyncio
import json

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConversionChunk:
    """Un fragmento del documento: su texto y la ruta de títulos de sección en la que está."""

    text: str
    headings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversionDocument:
    """Lo que el conversor dejó en el `.json` de un documento.

    Attributes:
        title (str | None): Título del documento, si lo dio el conversor.
        chunks (tuple[ConversionChunk, ...]): Fragmentos en el orden del documento.
        source_sha256 (str | None): Huella del original al convertirlo (`sha256_hash`), si está.
    """

    title: str | None
    chunks: tuple[ConversionChunk, ...]
    source_sha256: str | None = None

    @property
    def text(self) -> str:
        """El texto de todos los fragmentos unido por espacios (lo mismo que `read_conversion_json`)."""
        return " ".join(chunk.text for chunk in self.chunks)


def parse_conversion_document(payload: Any) -> ConversionDocument | None:
    """`ConversionDocument` a partir del JSON ya leído; `None` si no es un objeto.

    Example:
        >>> document = parse_conversion_document({"title": "Plan", "chunks": [{"text": "Hola", "headings": ["1. Objeto"]}, "suelto"]})
        >>> document.text, document.chunks[0].headings
        ('Hola suelto', ('1. Objeto',))
    """
    if not isinstance(payload, dict):
        return None
    chunks = []
    for chunk in payload.get("chunks") or []:
        if isinstance(chunk, dict):
            headings = chunk.get("headings") or []
            chunks.append(ConversionChunk(text=str(chunk.get("text", "")), headings=tuple(str(heading) for heading in headings if heading)))
        else:
            chunks.append(ConversionChunk(text=str(chunk)))
    title = payload.get("title")
    sha = payload.get("sha256_hash")
    return ConversionDocument(
        title=title if isinstance(title, str) else None, chunks=tuple(chunks), source_sha256=sha if isinstance(sha, str) else None
    )


async def read_conversion_document(json_path: str) -> ConversionDocument | None:
    """Lee el `.json` de conversión de `json_path`; `None` si no existe, no se puede leer o no es JSON válido."""
    try:
        raw = await asyncio.to_thread(Path(json_path).read_text, encoding="utf-8")
        return parse_conversion_document(json.loads(raw))
    except OSError:
        logger.warning(f"No se pudo leer el .json de conversión: {json_path}")
    except json.JSONDecodeError:
        logger.warning(f"El .json de conversión no es válido: {json_path}")
    return None


__all__ = ["ConversionChunk", "ConversionDocument", "parse_conversion_document", "read_conversion_document"]
