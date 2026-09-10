"""
Clasificación de documentos por dominio mediante reglas (Sub-fase A, sin IA).
"""

import asyncio
import json
import re

from pathlib import Path

from doc_organize.core.models import ConversionResult, DomainDocument
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_THRESHOLD = 0.5
_PATH_SIGNAL_BONUS = 0.25
_WORD_RE = re.compile(r"[a-záéíóúñü0-9]+")


async def read_conversion_json(json_path: str) -> tuple[str, str | None] | None:
    """Lee `chunks`/`title` del `.json` de conversión en `json_path`.

    Extraída para que tanto `DomainClassifier` (Sub-fase A) como `ContextBuilder`
    (orquestando la Sub-fase B) lean el `.json` con el mismo criterio — ver §2.4
    del `00_REQUEST.md` de la sesión sobre por qué el `.json`, no el `.md`.

    Returns:
        `(chunks_text, title)`, o `None` si el fichero no existe, no se puede leer
        o no es JSON válido — el llamador debe tratar el documento como artefacto
        incompleto (sin clasificar), nunca puntuarlo con contenido inventado.
    """
    try:
        raw = await asyncio.to_thread(Path(json_path).read_text, encoding="utf-8")
    except OSError:
        logger.warning(f"No se pudo leer el .json de conversión, documento sin clasificar: {json_path}")
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"El .json de conversión no es válido, documento sin clasificar: {json_path}")
        return None

    chunks = payload.get("chunks", [])
    texts = (chunk.get("text", "") if isinstance(chunk, dict) else str(chunk) for chunk in chunks)
    return " ".join(texts), payload.get("title")


def resolve_title_and_type(document: ConversionResult, title: str | None) -> tuple[str, str]:
    """Resuelve `(title, document_type)` para construir un `DomainDocument`.

    Compartida entre `DomainClassifier.classify()` (Sub-fase A) y
    `ContextBuilder._try_classify_document_with_ai()` (Sub-fase B) — antes cada
    una repetía el mismo fallback por su cuenta (AUDIT_CODE, sesión 2026-09-09).

    Args:
        document: Documento cuyo `markdown_path`/`source_path` usar como fallback.
        title: Título ya leído del `.json` de conversión (`read_conversion_json`),
            o `None` si no lo reportaba.

    Returns:
        `title` tal cual si no era `None`, o el `stem` de `markdown_path`; y la
        extensión de `source_path` en minúsculas sin el punto, o `"desconocido"`.
    """
    resolved_title = title or Path(document.markdown_path or "").stem
    document_type = Path(document.source_path).suffix.lstrip(".").lower() or "desconocido"
    return resolved_title, document_type


class DomainClassifier:
    """Clasifica `ConversionResult` en dominios por reglas, sin IA (Sub-fase A).

    Lee `chunks`/`title` del `.json` que `converter.py` ya genera por documento
    (pensado para RAG) en vez de reparsear el `.md` — decisión documentada en
    `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md` §2.4.

    Dos modos:

    - **Catálogo** (`candidate_domains` no vacío): solo asigna a uno de esos
      dominios — nunca inventa uno nuevo. El score por dominio es la fracción de
      palabras del slug encontradas en `title`+`chunks`, con un bonus si la
      carpeta contenedora del documento coincide con el slug (señal secundaria
      de ruta, §2.4).
    - **Descubrimiento** (`candidate_domains=None`): sin catálogo, la única señal
      de "evidencia real" disponible es la carpeta contenedora inmediata del
      documento — se convierte en el slug del dominio descubierto.

    Un documento cuyo mejor score queda por debajo de `threshold` (o que no tiene
    los tres artefactos completos) se devuelve como no clasificado — candidato a
    la Sub-fase B, nunca se le asigna un dominio a la fuerza.

    Attributes:
        candidate_domains (list[str] | None): Catálogo de slugs permitidos, o `None` para descubrir.
        threshold (float): Score mínimo (0-1) para clasificar sin pasar a la Sub-fase B.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> from doc_organize.core.models import ConversionResult
        >>> async def main():
        ...     doc = ConversionResult(
        ...         source_path="/docs/Ciberseguridad/informe.pdf",
        ...         markdown_path="/out/informe.md",
        ...         json_path="/out/informe.json",
        ...         success=True,
        ...     )
        ...     classifier = DomainClassifier()
        ...     classified, unclassified = await classifier.classify([doc])
        ...     return sorted(classified.keys()), unclassified
        >>> asyncio.run(main())  # doctest: +SKIP
        (['ciberseguridad'], [])
    """

    def __init__(self, candidate_domains: list[str] | None = None, threshold: float = _DEFAULT_THRESHOLD) -> None:
        self.candidate_domains = self._normalize_candidate_domains(candidate_domains)
        self.threshold = threshold
        self.logger = logger

    @staticmethod
    def _normalize_candidate_domains(candidate_domains: list[str] | None) -> list[str] | None:
        """Sanea cada dominio candidato con `_slugify()` antes de aceptarlo.

        Sin esto, un `candidate_domains` recibido tal cual desde una petición
        HTTP (`web/routes/context.py::BuildContextRequest`) acababa como
        `Domain.slug` sin validar, y de ahí directamente en rutas de disco
        (`ContextRegistry._domain_dir`, `Reorganizer.reorganize`,
        `MkDocsGenerator`) — un valor como `"../../otro-sitio"` podía escapar de
        `project.root_path` si llegaba a "ganar" la clasificación de algún
        documento (AUDIT_CODE, sesión 2026-09-08). `_slugify()` solo conserva
        caracteres de palabra, así que el resultado nunca contiene `/` ni `..`.
        """
        if candidate_domains is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in candidate_domains:
            slug = DomainClassifier._slugify(raw)
            if slug and slug not in seen:
                seen.add(slug)
                normalized.append(slug)
        return normalized

    async def classify(self, documents: list[ConversionResult]) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Clasifica `documents` en dominios.

        Returns:
            Tupla `(clasificados, sin_clasificar)`: `clasificados` mapea slug de
            dominio a la lista de `DomainDocument` asignados; `sin_clasificar` son
            los `ConversionResult` cuyo mejor score quedó por debajo de
            `self.threshold`, o a los que les falta algún artefacto — candidatos a
            la Sub-fase B (ver `00_REQUEST.md` §4, Reglas de negocio: nunca se
            reorganiza a medias un documento incompleto).
        """
        classified: dict[str, list[DomainDocument]] = {}
        unclassified: list[ConversionResult] = []

        for document in documents:
            if not document.success or not document.markdown_path or not document.json_path:
                unclassified.append(document)
                continue

            chunks_result = await read_conversion_json(document.json_path)
            if chunks_result is None:
                unclassified.append(document)
                continue
            chunks_text, title = chunks_result
            slug, score = self._best_domain(document, chunks_text, title)

            if slug is None or score < self.threshold:
                unclassified.append(document)
                continue

            resolved_title, document_type = resolve_title_and_type(document, title)
            classified.setdefault(slug, []).append(
                DomainDocument(
                    source_path=document.source_path,
                    markdown_path=document.markdown_path,
                    json_path=document.json_path,
                    images_dir=document.images_dir,
                    title=resolved_title,
                    document_type=document_type,
                    confidence=score,
                    classified_by="rules",
                )
            )

        return classified, unclassified

    def _best_domain(self, document: ConversionResult, chunks_text: str, title: str | None) -> tuple[str | None, float]:
        folder_slug = self._slugify(Path(document.source_path).parent.name)

        if self.candidate_domains:
            return self._best_from_catalog(folder_slug, chunks_text, title)
        return (folder_slug, 1.0) if folder_slug else (None, 0.0)

    def _best_from_catalog(self, folder_slug: str, chunks_text: str, title: str | None) -> tuple[str | None, float]:
        haystack = f"{title or ''} {chunks_text}".lower()
        best_slug: str | None = None
        best_score = 0.0

        for slug in self.candidate_domains or []:
            keywords = slug.replace("-", " ").split()
            if not keywords:
                continue
            hits = sum(1 for keyword in keywords if keyword in haystack)
            score = hits / len(keywords)
            if slug == folder_slug:
                score = min(1.0, score + _PATH_SIGNAL_BONUS)
            if score > best_score:
                best_slug, best_score = slug, score

        return best_slug, best_score

    @staticmethod
    def _slugify(name: str) -> str:
        return "-".join(_WORD_RE.findall(name.lower()))


__all__ = ["DomainClassifier", "read_conversion_json", "resolve_title_and_type"]
