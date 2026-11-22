"""
Índice de embeddings del proyecto (2.0.0, G4): un vector por texto, guardado para no volver a pedirlo.

Vive en `<raíz>/.doc_organize/embeddings/<huella del modelo>/`: `vectors.bin` (los vectores seguidos, `float32`; desde
2.2.0 se leen con numpy como una matriz, el mismo formato en disco) e `index.json` (la fila de cada clave y la
dimensión). La clave de un texto es la huella de
modelo, si se redactó y el texto: cambiar cualquiera de los tres da otra clave. Los vectores salen de `LlmClient.embed`,
que redacta las credenciales antes de enviar (D7), así que el índice nunca guarda un valor redactado; aun así deriva del
contenido de los documentos: trátalo como `Conversión/` (B11).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from doc_organize.ai.llm_client import LlmClient
from doc_organize.core.exceptions import AiResponseError
from doc_organize.core.models import AiTask
from doc_organize.utils.atomic_write import write_text_atomic
from doc_organize.utils.file_lock import exclusive_lock

#: Carpeta de los índices, relativa a la raíz del proyecto.
EMBEDDINGS_DIR = Path(".doc_organize") / "embeddings"
#: Textos por llamada a `LlmClient.embed`.
EMBED_BATCH_SIZE = 32
_FORMAT = 1


class EmbeddingIndex:
    """Vectores de un modelo de embeddings para un proyecto.

    Example:
        >>> import tempfile
        >>> index = EmbeddingIndex(tempfile.mkdtemp(), model="m", redacted=True)
        >>> index.key("hola") == index.key("hola"), index.key("hola") == EmbeddingIndex(".", model="otro", redacted=True).key("hola")
        (True, False)
    """

    def __init__(self, project_root: str | Path, *, model: str, redacted: bool) -> None:
        self.model = model
        self.redacted = redacted
        self.folder = Path(project_root) / EMBEDDINGS_DIR / hashlib.sha256(model.encode("utf-8")).hexdigest()[:16]
        self.embedded = 0  # textos pedidos al modelo (los demás salieron del índice)
        self.reused = 0

    def key(self, text: str) -> str:
        """La clave de `text` en este índice."""
        payload = json.dumps({"v": _FORMAT, "model": self.model, "redacted": self.redacted, "text": text}, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def vectors(self, llm: LlmClient, texts: Sequence[str], *, batch_size: int = EMBED_BATCH_SIZE, task: AiTask = "embed") -> list[list[float]]:
        """El vector de cada texto, en el mismo orden: los que ya están en el índice salen de él y los demás se piden a
        `llm` (en lotes de `batch_size`, con la tarea `task`) y se guardan.

        Raises:
            AiError: Ver `LlmClient.embed`.
            AiResponseError: El modelo devolvió vectores de otra dimensión que los del índice.
        """
        matrix = await self.matrix(llm, texts, batch_size=batch_size, task=task)
        return [[float(value) for value in row] for row in matrix]

    async def matrix(self, llm: LlmClient, texts: Sequence[str], *, batch_size: int = EMBED_BATCH_SIZE, task: AiTask = "embed") -> np.ndarray:
        """Como `vectors`, pero una matriz `float32` (una fila por texto) sin pasar por listas de Python (2.2.0): con miles
        de bloques de texto, las listas ocupan decenas de veces más memoria."""
        rows, stored = await asyncio.to_thread(self._read)
        keys = [self.key(text) for text in texts]
        missing = list(dict.fromkeys(key for key in keys if key not in rows))
        text_of = dict(zip(keys, texts, strict=True))
        fresh: dict[str, list[float]] = {}
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            for key, vector in zip(batch, await llm.embed([text_of[key] for key in batch], task=task), strict=True):
                fresh[key] = vector
        self.embedded += len(fresh)
        self.reused += sum(1 for key in dict.fromkeys(keys) if key in rows)
        if fresh:
            rows, stored = await asyncio.to_thread(self._write, fresh)
        if not keys:
            return np.zeros((0, stored.shape[1] if stored.ndim == 2 else 0), dtype=np.float32)
        return stored[[rows[key] for key in keys]]

    def _read(self) -> tuple[dict[str, int], np.ndarray]:
        """La fila de cada clave y la matriz de vectores (vacías si no hay índice o está dañado)."""
        empty: tuple[dict[str, int], np.ndarray] = ({}, np.zeros((0, 0), dtype=np.float32))
        index_path, vectors_path = self.folder / "index.json", self.folder / "vectors.bin"
        if not index_path.is_file() or not vectors_path.is_file() or index_path.is_symlink() or vectors_path.is_symlink():
            return empty
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            dimension, rows = int(index["dimension"]), {str(key): int(row) for key, row in dict(index["rows"]).items()}
            values = np.fromfile(vectors_path, dtype=np.float32)
        except (OSError, ValueError, KeyError, TypeError):
            return empty  # índice dañado: se vuelve a pedir lo que haga falta
        if index.get("format") != _FORMAT or dimension <= 0 or values.size != dimension * len(rows):
            return empty
        if rows and sorted(rows.values()) != list(range(len(rows))):
            return empty
        return rows, values.reshape(len(rows), dimension)

    def _write(self, fresh: dict[str, list[float]]) -> tuple[dict[str, int], np.ndarray]:
        self.folder.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.folder / "index.json"):
            rows, stored = self._read()  # otra construcción pudo añadir vectores mientras tanto
            new_keys = [key for key in fresh if key not in rows]
            dimensions = {len(fresh[key]) for key in new_keys} | ({stored.shape[1]} if rows else set())
            if len(dimensions) > 1:
                raise AiResponseError(f"Vectores de distinta dimensión en el índice de '{self.model}': {sorted(dimensions)}")
            if new_keys:
                added = np.asarray([fresh[key] for key in new_keys], dtype=np.float32)
                stored = np.concatenate([stored, added]) if rows else added
                rows = {**rows, **{key: len(rows) + offset for offset, key in enumerate(new_keys)}}
                temporary = self.folder / "vectors.bin.tmp"
                temporary.write_bytes(np.ascontiguousarray(stored, dtype=np.float32).tobytes())
                temporary.replace(self.folder / "vectors.bin")
                write_text_atomic(
                    self.folder / "index.json",
                    json.dumps({"format": _FORMAT, "model": self.model, "dimension": int(stored.shape[1]), "rows": rows}),
                )
            return rows, stored


@dataclass(frozen=True)
class EmbeddingIndexInfo:
    """Un índice de embeddings del proyecto (uno por modelo).

    Attributes:
        model (str | None): Modelo con el que se hizo (`None` si `index.json` no se puede leer).
        folder (str): Carpeta dentro de `.doc_organize/embeddings/`.
        vectors (int): Vectores guardados (uno por texto distinto: documentos y valores del catálogo).
        dimension (int | None): Dimensión de los vectores.
        size_bytes (int): Lo que ocupa en disco.
    """

    model: str | None
    folder: str
    vectors: int
    dimension: int | None
    size_bytes: int


def embedding_index_info(project_root: str | Path) -> list[EmbeddingIndexInfo]:
    """Los índices de embeddings del proyecto, uno por modelo, con su tamaño (para enseñarlo o decidir limpiarlo).

    Las claves son huellas de texto, no rutas: el índice no dice a qué documento pertenece cada vector.

    Example:
        >>> import tempfile
        >>> embedding_index_info(tempfile.mkdtemp())
        []
    """
    root = Path(project_root) / EMBEDDINGS_DIR
    if not root.is_dir() or root.is_symlink():
        return []
    found = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink()):
        size = sum(file.stat().st_size for file in folder.iterdir() if file.is_file() and not file.is_symlink())
        try:
            index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
            model, vectors, dimension = index.get("model"), len(index.get("rows", {})), index.get("dimension")
        except (OSError, ValueError, AttributeError):
            model, vectors, dimension = None, 0, None
        found.append(EmbeddingIndexInfo(model=model, folder=folder.name, vectors=vectors, dimension=dimension, size_bytes=size))
    return found


def clear_embedding_index(project_root: str | Path, *, model: str | None = None) -> int:
    """Borra el índice de `model` (o todos), para liberar espacio o empezar de cero: la siguiente construcción con
    `semantic=True` vuelve a pedir los vectores. No lo llames mientras se construye el contexto. Devuelve los índices
    borrados. No sigue enlaces simbólicos.

    Example:
        >>> import tempfile
        >>> clear_embedding_index(tempfile.mkdtemp())
        0
    """
    root = Path(project_root) / EMBEDDINGS_DIR
    if not root.is_dir() or root.is_symlink():
        return 0
    targets = [EmbeddingIndex(project_root, model=model, redacted=True).folder] if model is not None else list(root.iterdir())
    removed = 0
    for folder in targets:
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder)
            removed += 1
    return removed


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Similitud del coseno entre dos vectores (0 si alguno es nulo).

    Example:
        >>> cosine([1.0, 0.0], [1.0, 0.0]), cosine([1.0, 0.0], [0.0, 1.0])
        (1.0, 0.0)
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


__all__ = ["EMBEDDINGS_DIR", "EMBED_BATCH_SIZE", "EmbeddingIndex", "EmbeddingIndexInfo", "clear_embedding_index", "cosine", "embedding_index_info"]
