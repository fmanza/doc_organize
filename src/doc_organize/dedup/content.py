"""
Duplicados por contenido (2.2.0): sobre el texto ya convertido (`Conversión/`), no sobre el fichero.

`DeduplicationManager.find_duplicates` compara metadatos (hash, nombre); esto compara lo que dicen los documentos, en dos
pasadas sobre el Markdown de cada uno:

1. **Mismo contenido** (`DuplicateReason.SAME_CONTENT`, sin IA): el mismo texto normalizado (sin formato, mayúsculas
   ni puntuación) en ficheros distintos, p. ej. un `.docx` y el `.pdf` que se generó de él.
2. **Contenido parecido** (`DuplicateReason.SEMANTIC_CONTENT_MATCH`, opt-in, con la tarea de IA `dedup`): embeddings
   por bloques de texto. Primero un vector por documento (la media de sus bloques) elige los vecinos más cercanos de
   cada uno; después, solo para esos candidatos, se comparan bloque a bloque y la similitud del par es la mejor de las
   dos direcciones (cuánto de A está en B y cuánto de B en A): así también sale un documento contenido en otro.

De cada par parecido se calcula además la similitud de texto (Jaccard de trozos de 5 palabras): alta, es casi el mismo
texto; baja con la semántica alta, es un texto reescrito o la misma plantilla con otros datos. Una persona decide con
las dos.

Los grupos se forman de forma voraz y determinista: un documento entra en un grupo solo si llega al umbral con **todos**
sus miembros (sin las cadenas A~B~C de las componentes conexas, que con el contenido juntan documentos que no se
parecen). Nunca se resuelven solos: como `FUZZY_NAME_MATCH`, solo con una persona eligiendo qué conservar
(`DeduplicationManager.move_group(..., conversions=...)` mueve también la conversión del descartado).

Los vectores se guardan en el índice de embeddings del proyecto (`EmbeddingIndex`): repetir una búsqueda no los vuelve a
pedir. Salen de `LlmClient.embed`, que redacta las credenciales antes de enviar (D7); aun así, a la tarea `dedup` va el
texto **completo** de cada documento (al contexto semántico solo va un extracto): usa un modelo local.
"""

from __future__ import annotations

import asyncio
import hashlib
import re

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from doc_organize.core.exceptions import AiConfigurationError
from doc_organize.core.models import ClassificationDecision, ConversionResult, DocumentMetadata, DuplicateGroup, DuplicateReason
from doc_organize.dedup.deduplication import DeduplicationManager
from doc_organize.utils.logging import get_logger

if TYPE_CHECKING:
    from doc_organize.ai.llm_client import LlmClient

logger = get_logger(__name__)

#: Similitud semántica mínima por defecto. Los modelos de embeddings dan valores altos incluso a documentos distintos del
#: mismo tema: por debajo de ~0,85 salen sobre todo documentos que solo comparten temática.
DEFAULT_SEMANTIC_THRESHOLD = 0.90
#: Palabras por bloque y solape entre bloques (unas 800 palabras caben con holgura en 8.192 tokens de `bge-m3`).
DEFAULT_CHUNK_WORDS = 800
DEFAULT_CHUNK_OVERLAP = 100
#: Vecinos de cada documento que se comparan bloque a bloque.
DEFAULT_NEIGHBOURS = 10
#: Un documento con menos palabras no se compara (una portada o un fichero casi vacío se parecen a cualquier cosa).
DEFAULT_MIN_WORDS = 30
#: Bloques por llamada a `/embeddings` (un modelo local en CPU tarda con lotes grandes de bloques largos).
DEFAULT_BATCH_SIZE = 8
#: Candidatos: vecinos cuya similitud entre documentos llega al umbral menos este margen (la de bloques puede subir).
PREFILTER_MARGIN = 0.10
#: Palabras de cada trozo de la similitud de texto.
SHINGLE_WORDS = 5

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_MARKUP = re.compile(r"[#*_`|>~\\]+|^-{3,}$|^:?-{3,}:?(\s*\|\s*:?-{3,}:?)*$", re.MULTILINE)
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class ContentDocument:
    """Un documento para comparar por contenido: su original y su conversión.

    Attributes:
        metadata (DocumentMetadata): El original (el que se conserva o se mueve).
        conversion (ConversionResult): Su conversión; se lee `markdown_path`.
    """

    metadata: DocumentMetadata
    conversion: ConversionResult


@dataclass
class ContentDuplicateReport:
    """Resultado de `ContentDuplicateFinder.find`.

    Attributes:
        groups (list[DuplicateGroup]): Grupos por contenido (`SAME_CONTENT` primero, después `SEMANTIC_CONTENT_MATCH`
            de más a menos parecidos).
        not_compared (list[str]): `full_path` de los que no se pudieron comparar (sin conversión, `.md` ilegible o con
            menos de `min_words` palabras).
        compared (int): Documentos comparados (uno por huella: los duplicados exactos los agrupa `find_duplicates`).
        semantic (bool): Se hizo la pasada semántica.
        embedded (int): Bloques cuyos vectores se pidieron al modelo.
        reused (int): Bloques cuyos vectores salieron del índice.
    """

    groups: list[DuplicateGroup] = field(default_factory=list)
    not_compared: list[str] = field(default_factory=list)
    compared: int = 0
    semantic: bool = False
    embedded: int = 0
    reused: int = 0


@dataclass(frozen=True)
class _Text:
    """El texto de un documento listo para comparar."""

    document: ContentDocument
    tokens: list[str]  # palabras del texto sin formato (para los bloques que van al modelo)
    words: list[str]  # palabras normalizadas (huella y similitud de texto)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(" ".join(self.words).encode("utf-8")).hexdigest()

    def shingles(self) -> set[str]:
        words = self.words
        if len(words) <= SHINGLE_WORDS:
            return {" ".join(words)}
        return {" ".join(words[index : index + SHINGLE_WORDS]) for index in range(len(words) - SHINGLE_WORDS + 1)}


def plain_text(markdown: str) -> str:
    """El texto de un Markdown de Docling sin imágenes, enlaces, comentarios, etiquetas ni marcas de formato.

    Example:
        >>> plain_text("# Título\\n\\n**Texto** con [enlace](http://x) y ![img](a.png) <!-- image -->")
        'Título\\n\\nTexto con enlace y'
    """
    text = _COMMENT.sub(" ", markdown)
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    text = _MARKUP.sub(" ", text)
    return "\n".join(" ".join(line.split()) for line in text.splitlines()).strip()


def normalized_words(text: str) -> list[str]:
    """Las palabras de `text` en minúsculas y sin puntuación (la huella de «mismo contenido»).

    Example:
        >>> normalized_words("El Plan, v2: ¡APROBADO!")
        ['el', 'plan', 'v2', 'aprobado']
    """
    return _WORD.findall(text.casefold())


def chunks(tokens: Sequence[str], *, size: int = DEFAULT_CHUNK_WORDS, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Bloques de `size` palabras con `overlap` de solape (uno solo si el texto cabe).

    Example:
        >>> chunks("a b c d e".split(), size=3, overlap=1)
        ['a b c', 'c d e']
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Hace falta size > 0 y 0 <= overlap < size")
    if len(tokens) <= size:
        return [" ".join(tokens)]
    step = size - overlap
    starts = list(range(0, len(tokens) - overlap, step))
    return [" ".join(tokens[start : start + size]) for start in starts if start < len(tokens)]


def pair_similarity(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Similitud entre dos documentos dados sus bloques (filas normalizadas): cuánto de `a` está en `b` (la media, por
    bloque de `a`, del bloque más parecido de `b`) y al revés.

    Example:
        >>> a = np.array([[1.0, 0.0], [0.0, 1.0]]); b = np.array([[1.0, 0.0]])
        >>> [round(value, 2) for value in pair_similarity(a, b)]  # medio `a` está en `b`; todo `b` está en `a`
        [0.5, 1.0]
    """
    matrix = a @ b.T
    return float(np.clip(matrix.max(axis=1).mean(), 0.0, 1.0)), float(np.clip(matrix.max(axis=0).mean(), 0.0, 1.0))


def jaccard(a: set[str], b: set[str]) -> float:
    """Similitud de Jaccard de dos conjuntos (0 si los dos están vacíos)."""
    union = len(a | b)
    return len(a & b) / union if union else 0.0


class ContentDuplicateFinder:
    """Busca duplicados por contenido entre documentos ya convertidos.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> from doc_organize.core.models import ConversionResult, DocumentMetadata
        >>> root = Path(tempfile.mkdtemp())
        >>> def document(name, text):
        ...     (root / f"{name}.md").write_text(text, encoding="utf-8")
        ...     metadata = DocumentMetadata(full_path=str(root / name), display_name=name, extension=name.split(".")[-1],
        ...                                 size_bytes=1, modified_time=1.0, sha256_hash=name.encode().hex().ljust(64, "0"))
        ...     return ContentDocument(metadata, ConversionResult(source_path=str(root / name), markdown_path=str(root / f"{name}.md"),
        ...                                                       json_path=None, success=True))
        >>> text = "Procedimiento de alta de proveedores con los pasos de revisión y aprobación del contrato. " * 5
        >>> report = asyncio.run(ContentDuplicateFinder(root).find([document("a.docx", text), document("a.pdf", "# " + text)]))
        >>> [group.reason.value for group in report.groups], report.compared
        (['same_content'], 2)
    """

    def __init__(
        self,
        project_root: str | Path,
        llm: LlmClient | None = None,
        *,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
        chunk_words: int = DEFAULT_CHUNK_WORDS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        neighbours: int = DEFAULT_NEIGHBOURS,
        min_words: int = DEFAULT_MIN_WORDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        read_concurrency: int = 8,
    ) -> None:
        """
        Args:
            project_root: Raíz del proyecto (el índice de embeddings vive en `.doc_organize/embeddings/`).
            llm: Cliente de IA para la pasada semántica (tarea `dedup`, con modelo propio); sin él solo «mismo
                contenido».
            semantic_threshold: Similitud mínima (0-1] para «contenido parecido».
            chunk_words, chunk_overlap: Tamaño y solape de los bloques que van al modelo.
            neighbours: Vecinos de cada documento que se comparan bloque a bloque.
            min_words: Palabras mínimas para comparar un documento.
            batch_size: Bloques por llamada a `/embeddings`.
            read_concurrency: `.md` que se leen a la vez.

        Raises:
            ValueError: Algún parámetro fuera de rango.
        """
        if not 0.0 < semantic_threshold <= 1.0:
            raise ValueError("semantic_threshold tiene que estar en (0, 1]")
        if chunk_words <= 0 or not 0 <= chunk_overlap < chunk_words:
            raise ValueError("Hace falta chunk_words > 0 y 0 <= chunk_overlap < chunk_words")
        if neighbours < 1 or min_words < 1 or batch_size < 1 or read_concurrency < 1:
            raise ValueError("neighbours, min_words, batch_size y read_concurrency tienen que ser >= 1")
        self.project_root = Path(project_root)
        self.llm = llm
        self.semantic_threshold = semantic_threshold
        self.chunk_words = chunk_words
        self.chunk_overlap = chunk_overlap
        self.neighbours = neighbours
        self.min_words = min_words
        self.batch_size = batch_size
        self.read_concurrency = read_concurrency

    async def find(self, documents: Sequence[ContentDocument], *, semantic: bool = False) -> ContentDuplicateReport:
        """Agrupa `documents` por contenido.

        Los duplicados exactos (mismo `sha256_hash`) cuentan una sola vez, con el primero por ruta: esos los agrupa
        `DeduplicationManager.find_duplicates`. Los miembros de un grupo «mismo contenido» no pasan a la semántica.

        Args:
            documents: Originales con su conversión.
            semantic: Hacer también la pasada semántica (necesita `llm` con modelo propio para `dedup`).

        Raises:
            AiConfigurationError: `semantic` sin `llm` o sin modelo propio para la tarea `dedup` (es independiente de los
                embeddings del contexto: no se usa el de `embed`).
            AiError: Ver `LlmClient.embed` (red, clave, respuesta).
        """
        if semantic:
            self._check_llm()
        report = ContentDuplicateReport(semantic=semantic)
        unique = self._one_per_hash(documents)
        texts = await self._read_all(unique, report)
        report.compared = len(texts)

        by_fingerprint: dict[str, list[_Text]] = {}
        for text in texts:
            by_fingerprint.setdefault(text.fingerprint, []).append(text)
        grouped: set[str] = set()
        for members in by_fingerprint.values():
            if len(members) > 1:
                report.groups.append(
                    _group([text.document.metadata for text in members], DuplicateReason.SAME_CONTENT, similarity=1.0, lexical=1.0, contained=False)
                )
                grouped.update(text.document.metadata.full_path for text in members)

        if semantic:
            remaining = [text for text in texts if text.document.metadata.full_path not in grouped]
            report.groups.extend(await self._semantic_groups(remaining, report))
        logger.info(
            f"Duplicados por contenido: {len(report.groups)} grupo(s) entre {report.compared} documento(s)"
            + (f", {len(report.not_compared)} sin comparar" if report.not_compared else "")
        )
        return report

    # --- Internos ------------------------------------------------------------------------------------------------------

    def _check_llm(self) -> None:
        if self.llm is None:
            raise AiConfigurationError("La búsqueda de duplicados por contenido parecido necesita un cliente de IA.")
        if "dedup" not in self.llm.settings.tasks:
            raise AiConfigurationError(
                "La búsqueda de duplicados por contenido parecido necesita un modelo de embeddings propio para la tarea "
                "'dedup' (DOC_ORGANIZE_LITELLM_MODEL_DEDUP); no usa el de 'embed'."
            )

    @staticmethod
    def _one_per_hash(documents: Sequence[ContentDocument]) -> list[ContentDocument]:
        seen: set[str] = set()
        unique = []
        for document in sorted(documents, key=lambda item: item.metadata.full_path):
            if document.metadata.sha256_hash in seen:
                continue
            seen.add(document.metadata.sha256_hash)
            unique.append(document)
        return unique

    async def _read_all(self, documents: list[ContentDocument], report: ContentDuplicateReport) -> list[_Text]:
        semaphore = asyncio.Semaphore(self.read_concurrency)

        async def read(document: ContentDocument) -> _Text | None:
            path = document.conversion.markdown_path
            if not document.conversion.success or not path:
                return None
            async with semaphore:
                try:
                    markdown = await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    logger.warning(f"No se pudo leer la conversión de '{document.metadata.display_name}': no se compara")
                    return None
            plain = plain_text(markdown)
            words = normalized_words(plain)
            if len(words) < self.min_words:
                return None
            return _Text(document=document, tokens=plain.split(), words=words)

        results = await asyncio.gather(*(read(document) for document in documents))
        texts = []
        for document, text in zip(documents, results, strict=True):
            if text is None:
                report.not_compared.append(document.metadata.full_path)
            else:
                texts.append(text)
        return texts

    async def _semantic_groups(self, texts: list[_Text], report: ContentDuplicateReport) -> list[DuplicateGroup]:
        if len(texts) < 2:
            return []
        from doc_organize.ai.embeddings import EmbeddingIndex

        assert self.llm is not None  # `_check_llm`
        owners: list[int] = []
        pieces: list[str] = []
        for position, text in enumerate(texts):
            for piece in chunks(text.tokens, size=self.chunk_words, overlap=self.chunk_overlap):
                owners.append(position)
                pieces.append(piece)
        index = EmbeddingIndex(self.project_root, model=self.llm.model_for("dedup"), redacted=self.llm.settings.redact_credentials)
        matrix = await index.matrix(self.llm, pieces, batch_size=self.batch_size, task="dedup")
        report.embedded, report.reused = index.embedded, index.reused
        blocks = _blocks_by_document(_normalize(matrix), np.asarray(owners), len(texts))

        scores: dict[tuple[int, int], tuple[float, bool]] = {}
        for i, j in self._candidates(blocks):
            forward, backward = pair_similarity(blocks[i], blocks[j])
            score = max(forward, backward)
            scores[(i, j)] = (score, min(forward, backward) < self.semantic_threshold <= score)
        return [
            _group(
                [texts[member].document.metadata for member in members],
                DuplicateReason.SEMANTIC_CONTENT_MATCH,
                similarity=round(min(scores[pair][0] for pair in _pairs(members)), 4),
                lexical=round(min(jaccard(texts[a].shingles(), texts[b].shingles()) for a, b in _pairs(members)), 4),
                contained=any(scores[pair][1] for pair in _pairs(members)),
            )
            for members in _greedy_groups(scores, self.semantic_threshold)
        ]

    def _candidates(self, blocks: list[np.ndarray]) -> list[tuple[int, int]]:
        """Pares `(i, j)` con `i < j` que se comparan bloque a bloque: los `neighbours` más parecidos de cada documento
        (por su vector medio) que llegan al umbral menos `PREFILTER_MARGIN`. Por tramos de filas para no crear la
        matriz completa de documentos."""
        means = _normalize(np.vstack([block.mean(axis=0) for block in blocks]))
        floor = self.semantic_threshold - PREFILTER_MARGIN
        pairs: set[tuple[int, int]] = set()
        step = 512
        for start in range(0, len(means), step):
            similarity = means[start : start + step] @ means.T
            for offset, row in enumerate(similarity):
                i = start + offset
                row[i] = -1.0
                nearest = np.argsort(-row, kind="stable")[: self.neighbours]
                pairs.update((min(i, int(j)), max(i, int(j))) for j in nearest if row[j] >= floor)
        return sorted(pairs)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized: np.ndarray = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
    return normalized


def _blocks_by_document(matrix: np.ndarray, owners: np.ndarray, count: int) -> list[np.ndarray]:
    return [matrix[owners == position] for position in range(count)]


def _pairs(members: Sequence[int]) -> list[tuple[int, int]]:
    ordered = sorted(members)
    return [(a, b) for index, a in enumerate(ordered) for b in ordered[index + 1 :]]


def _greedy_groups(scores: dict[tuple[int, int], tuple[float, bool]], threshold: float) -> list[list[int]]:
    """Grupos en los que **todos** los pares llegan al umbral: se recorren los pares del más al menos parecido; un
    documento sin grupo entra en el de su pareja si llega al umbral con todos sus miembros. Determinista (empates por
    posición). Los grupos salen del más al menos parecido."""

    def similar(a: int, b: int) -> bool:
        pair = (min(a, b), max(a, b))
        return pair in scores and scores[pair][0] >= threshold

    group_of: dict[int, int] = {}
    groups: list[list[int]] = []
    for (i, j), _ in sorted(scores.items(), key=lambda item: (-item[1][0], item[0])):
        if not similar(i, j):
            continue
        gi, gj = group_of.get(i), group_of.get(j)
        if gi is None and gj is None:
            group_of[i] = group_of[j] = len(groups)
            groups.append([i, j])
        elif (gi is None) != (gj is None):
            target, newcomer = (gj, i) if gi is None else (gi, j)
            assert target is not None
            if all(similar(member, newcomer) for member in groups[target]):
                group_of[newcomer] = target
                groups[target].append(newcomer)
    return [sorted(group) for group in groups]


def _group(docs: list[DocumentMetadata], reason: DuplicateReason, *, similarity: float, lexical: float, contained: bool) -> DuplicateGroup:
    """Grupo con el mismo criterio que `find_duplicates`: se conserva el más antiguo y el id es estable."""
    canonical = min(docs, key=lambda doc: (doc.modified_time, doc.full_path))
    return DuplicateGroup(
        group_id=DeduplicationManager.stable_group_id(docs, reason),
        canonical_doc=canonical,
        duplicates=[doc for doc in docs if doc.full_path != canonical.full_path],
        reason=reason,
        similarity=similarity,
        lexical_similarity=lexical,
        contained=contained,
    )


async def exclude_from_context(
    project_root: str | Path, groups: Sequence[DuplicateGroup], *, roots: Sequence[str] | None = None, author: str = "dedup"
) -> int:
    """Excluye del contexto los descartados de `groups` con una decisión `exclude` por documento (2.2.0).

    Para el modo `copy` de la resolución, en el que el original se queda donde está y la siguiente construcción del
    contexto lo volvería a incluir. Con `move` no hace falta: el original y su conversión salen de su sitio. Las decisiones
    llevan la huella del original (si cambia, dejan de aplicarse) y se pueden revocar como cualquier otra.

    Como todas las decisiones de clasificación, solo se aplican al construir **con manifiesto de taxonomía**; sin él
    quedan en `Context.stale_decisions` con `no_manifest`.

    Args:
        project_root: Raíz del proyecto (`.doc_organize/decisions.json`).
        groups: Grupos resueltos; se excluyen todos menos el que se conserva (`user_choice` o `canonical_doc`).
        roots: Las mismas raíces de escaneo que se pasan a `ContextBuilder.build(scan_roots=)` (la clave de cada
            documento es su ruta relativa a ellas).
        author: Quién figura como autor de las decisiones.

    Returns:
        Decisiones guardadas.
    """
    from doc_organize.context.decisions import ClassificationDecisionStore
    from doc_organize.context.evaluation import document_keys

    discarded: list[tuple[DocumentMetadata, DocumentMetadata]] = []
    for group in groups:
        keep = group.user_choice or group.canonical_doc
        discarded.extend((doc, keep) for doc in [group.canonical_doc, *group.duplicates] if doc.full_path != keep.full_path)
    if not discarded:
        return 0
    keys = document_keys([path for doc, keep in discarded for path in (doc.full_path, keep.full_path)], roots)
    store = ClassificationDecisionStore(project_root)
    for doc, keep in discarded:
        await store.add(
            ClassificationDecision(
                document_key=keys[doc.full_path],
                source_sha256=doc.sha256_hash,
                action="exclude",
                author=author,
                reason=f"Duplicado por contenido de «{keys[keep.full_path]}»",
            )
        )
    return len(discarded)


__all__ = [
    "DEFAULT_SEMANTIC_THRESHOLD",
    "ContentDocument",
    "ContentDuplicateFinder",
    "ContentDuplicateReport",
    "chunks",
    "exclude_from_context",
    "jaccard",
    "normalized_words",
    "pair_similarity",
    "plain_text",
]
