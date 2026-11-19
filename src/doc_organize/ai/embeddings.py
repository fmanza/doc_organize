"""
Índice de embeddings del proyecto (2.0.0, G4): un vector por texto, guardado para no volver a pedirlo.

Vive en `<raíz>/.doc_organize/embeddings/<huella del modelo>/`: `vectors.bin` (los vectores seguidos, `float32` del
módulo `array`, sin numpy) e `index.json` (la fila de cada clave y la dimensión). La clave de un texto es la huella de
modelo, si se redactó y el texto: cambiar cualquiera de los tres da otra clave. Los vectores salen de `LlmClient.embed`,
que redacta las credenciales antes de enviar (D7), así que el índice nunca guarda un valor redactado; aun así deriva del
contenido de los documentos: trátalo como `Conversión/` (B11).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math

from array import array
from collections.abc import Sequence
from pathlib import Path

from doc_organize.ai.llm_client import LlmClient
from doc_organize.core.exceptions import AiResponseError
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

    async def vectors(self, llm: LlmClient, texts: Sequence[str], *, batch_size: int = EMBED_BATCH_SIZE) -> list[list[float]]:
        """El vector de cada texto, en el mismo orden: los que ya están en el índice salen de él y los demás se piden a
        `llm` (en lotes de `batch_size`) y se guardan.

        Raises:
            AiError: Ver `LlmClient.embed`.
            AiResponseError: El modelo devolvió vectores de otra dimensión que los del índice.
        """
        stored = await asyncio.to_thread(self._read)
        keys = [self.key(text) for text in texts]
        missing = list(dict.fromkeys(key for key in keys if key not in stored))
        text_of = dict(zip(keys, texts, strict=True))
        fresh: dict[str, list[float]] = {}
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            for key, vector in zip(batch, await llm.embed([text_of[key] for key in batch]), strict=True):
                fresh[key] = vector
        self.embedded += len(fresh)
        self.reused += sum(1 for key in dict.fromkeys(keys) if key in stored)
        if fresh:
            await asyncio.to_thread(self._write, fresh)
            stored.update(fresh)
        return [stored[key] for key in keys]

    def _read(self) -> dict[str, list[float]]:
        index_path, vectors_path = self.folder / "index.json", self.folder / "vectors.bin"
        if not index_path.is_file() or not vectors_path.is_file() or index_path.is_symlink() or vectors_path.is_symlink():
            return {}
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            dimension, rows = int(index["dimension"]), dict(index["rows"])
            values = array("f")
            values.frombytes(vectors_path.read_bytes())
        except (OSError, ValueError, KeyError, TypeError):
            return {}  # índice dañado: se vuelve a pedir lo que haga falta
        if index.get("format") != _FORMAT or len(values) != dimension * len(rows):
            return {}
        return {key: values[row * dimension : (row + 1) * dimension].tolist() for key, row in rows.items()}

    def _write(self, fresh: dict[str, list[float]]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.folder / "index.json"):
            stored = self._read()  # otra construcción pudo añadir vectores mientras tanto
            stored.update(fresh)
            dimensions = {len(vector) for vector in stored.values()}
            if len(dimensions) != 1:
                raise AiResponseError(f"Vectores de distinta dimensión en el índice de '{self.model}': {sorted(dimensions)}")
            rows = {key: row for row, key in enumerate(stored)}
            values = array("f", (value for vector in stored.values() for value in vector))
            temporary = self.folder / "vectors.bin.tmp"
            temporary.write_bytes(values.tobytes())
            temporary.replace(self.folder / "vectors.bin")
            write_text_atomic(
                self.folder / "index.json", json.dumps({"format": _FORMAT, "model": self.model, "dimension": dimensions.pop(), "rows": rows})
            )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Similitud del coseno entre dos vectores (0 si alguno es nulo).

    Example:
        >>> cosine([1.0, 0.0], [1.0, 0.0]), cosine([1.0, 0.0], [0.0, 1.0])
        (1.0, 0.0)
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


__all__ = ["EMBEDDINGS_DIR", "EMBED_BATCH_SIZE", "EmbeddingIndex", "cosine"]
