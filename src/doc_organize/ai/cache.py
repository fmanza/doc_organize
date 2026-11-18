"""
Caché de resultados de IA (2.0.0, G1): reconstruir un contexto sin cambios no vuelve a llamar al modelo.

Cada resultado se guarda bajo la huella de **lo que se enviaría**: tarea, modelo, mensajes ya redactados (prompt,
catálogo, perfil y documento) y esquema de la respuesta. Si cambia cualquiera de ellos (otro prompt o versión, otro
modelo, un catálogo distinto, el documento, la redacción activada o no), la huella es otra y se vuelve a preguntar
(auditoría B9). Lo guardado es el JSON que devolvió el modelo; al leerlo se valida otra vez con el mismo `parse`.

Vive en `<raíz del proyecto>/.doc_organize/ai_cache/`, con la misma sensibilidad que `Conversión/` (B11): guarda
respuestas derivadas del contenido (justificaciones, descripciones), del texto ya redactado.
"""

import hashlib
import json
import os
import time

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from doc_organize.utils.atomic_write import write_text_atomic
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

#: Carpeta de la caché, relativa a la raíz del proyecto.
AI_CACHE_DIR = Path(".doc_organize") / "ai_cache"
#: Versión del formato de la clave y de las entradas: cambiarla invalida toda la caché.
CACHE_FORMAT_VERSION = 1


def cache_key(task: str, model: str, messages: Sequence[dict[str, Any]], schema: dict[str, Any], *, redacted: bool) -> str:
    """Huella SHA-256 de una petición: tarea, modelo, mensajes tal como salen, esquema y si se redactó.

    Example:
        >>> a = cache_key("classify", "m", [{"role": "user", "content": "x"}], {"type": "object"}, redacted=True)
        >>> b = cache_key("classify", "m", [{"role": "user", "content": "y"}], {"type": "object"}, redacted=True)
        >>> len(a), a == b
        (64, False)
    """
    payload = {"v": CACHE_FORMAT_VERSION, "task": task, "model": model, "messages": list(messages), "schema": schema, "redacted": redacted}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class AiResultCache:
    """Resultados de IA de un proyecto, uno por fichero (`<clave[:2]>/<clave>.json`).

    Al leer una entrada se actualiza su fecha de modificación: `prune_ai_cache` borra las que llevan tiempo sin usarse.
    Una entrada ilegible se ignora (cuenta como fallo de caché). Nunca se escribe a través de un enlace simbólico.

    Example:
        >>> import tempfile
        >>> cache = AiResultCache(tempfile.mkdtemp())
        >>> cache.put("ab" * 32, {"ok": True}, response_format="json_schema")
        >>> cache.get("ab" * 32)
        ({'ok': True}, 'json_schema')
        >>> cache.get("cd" * 32) is None
        True
    """

    def __init__(self, project_root: Path | str) -> None:
        self.directory = Path(project_root) / AI_CACHE_DIR

    def _path(self, key: str) -> Path:
        if len(key) != 64 or not all(char in "0123456789abcdef" for char in key):
            raise ValueError("clave de caché no válida")
        return self.directory / key[:2] / f"{key}.json"

    def has(self, key: str) -> bool:
        """Si hay entrada para `key` (sin leerla ni marcarla como usada)."""
        return self._path(key).is_file()

    def get(self, key: str) -> tuple[Any, str] | None:
        """`(datos, formato de respuesta)` de `key`, o `None` si no está o no se puede leer."""
        path = self._path(key)
        try:
            if path.is_symlink():
                return None
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(entry, dict) or entry.get("v") != CACHE_FORMAT_VERSION or "data" not in entry:
            return None
        try:
            os.utime(path)  # usada: no la borra `prune_ai_cache`
        except OSError:
            pass
        return entry["data"], str(entry.get("response_format", "json_schema"))

    def put(self, key: str, data: Any, *, response_format: str) -> None:
        """Guarda `data` (el JSON que devolvió el modelo). Un fallo al escribir se registra y no interrumpe nada."""
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.parent.is_symlink() or path.is_symlink():
                logger.warning("La caché de IA pasa por un enlace simbólico: no se escribe")
                return
            write_text_atomic(path, json.dumps({"v": CACHE_FORMAT_VERSION, "response_format": response_format, "data": data}, ensure_ascii=False))
        except OSError as exc:
            logger.warning(f"No se pudo guardar un resultado en la caché de IA: {type(exc).__name__}")


def prune_ai_cache(project_root: Path | str, *, max_age_days: float = 90.0) -> int:
    """Borra las entradas de la caché de IA de un proyecto que llevan más de `max_age_days` sin usarse.

    Returns:
        Entradas borradas.

    Example:
        >>> import tempfile
        >>> prune_ai_cache(tempfile.mkdtemp())
        0
    """
    directory = Path(project_root) / AI_CACHE_DIR
    if not directory.is_dir() or directory.is_symlink():
        return 0
    limit = time.time() - max_age_days * 86400
    removed = 0
    for path in directory.glob("*/*.json"):
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < limit:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


__all__ = ["AI_CACHE_DIR", "AiResultCache", "cache_key", "prune_ai_cache"]
