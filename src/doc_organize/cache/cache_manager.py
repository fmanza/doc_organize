"""
Cache transaccional (SQLite + WAL) de hashes de documentos (REQ-006).
"""

from pathlib import Path
from typing import Self

import aiosqlite

from doc_organize.core.exceptions import CacheError
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentMetadata, DocumentStatus
from doc_organize.utils.hash_utils import hash_file
from doc_organize.utils.logging import get_logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    file_path TEXT PRIMARY KEY,
    sha256_hash TEXT NOT NULL,
    timestamp REAL NOT NULL,
    status TEXT NOT NULL,
    conversion_status TEXT
)
"""

_UPSERT = """
INSERT INTO cache_entries (file_path, sha256_hash, timestamp, status, conversion_status)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(file_path) DO UPDATE SET
    sha256_hash=excluded.sha256_hash,
    timestamp=excluded.timestamp,
    status=excluded.status,
    conversion_status=excluded.conversion_status
"""


def _py_lower(value: str | None) -> str | None:
    """Funcion SQL `py_lower`: plegado a minusculas Unicode-aware (registrada por conexion)."""
    return value.lower() if value is not None else None


def _like_pattern(search: str) -> str:
    """Envuelve `search` en comodines `%...%` escapando `\\`, `%` y `_` (literales de LIKE)."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class CacheManager:
    """Gestiona el cache transaccional de hashes en `cache.db` (SQLite, WAL).

    Unica fuente de verdad de hashing: `compute_hash()` delega en
    `utils.hash_utils.hash_file()`, nunca reimplementa SHA-256. El modo WAL
    permite lecturas concurrentes mientras la web app escribe.

    Attributes:
        db_path (Path): Ruta al archivo SQLite de cache.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio
        >>> async def main():
        ...     async with CacheManager("./cache.db") as cache:
        ...         entries = await cache.load_cache()
        >>> asyncio.run(main())
    """

    def __init__(self, db_path: str | Path = "cache.db") -> None:
        self.db_path = Path(db_path)
        self.logger = get_logger(__name__)
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Self:
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()
        # SQLite LIKE/LOWER() solo pliegan mayusculas para ASCII: sin esto, buscar
        # "cafe" no encontraria "CAFE" en nombres de archivo en espanol con tildes.
        await self._conn.create_function("py_lower", 1, _py_lower, deterministic=True)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise CacheError("CacheManager debe usarse como context manager async ('async with').")
        return self._conn

    async def load_cache(self) -> dict[str, CacheEntry]:
        """Lee todas las entradas de `cache.db`."""
        cache: dict[str, CacheEntry] = {}
        async with self._connection.execute("SELECT file_path, sha256_hash, timestamp, status, conversion_status FROM cache_entries") as cursor:
            async for file_path, sha256_hash, timestamp, status, conversion_status in cursor:
                cache[file_path] = CacheEntry(
                    file_path=file_path,
                    sha256_hash=sha256_hash,
                    timestamp=timestamp,
                    status=DocumentStatus(status),
                    conversion_status=ConversionStatus(conversion_status) if conversion_status else None,
                )
        return cache

    async def count_entries(self, search: str | None = None) -> int:
        """Cuenta entradas de `cache_entries`, opcionalmente filtradas por `search`.

        Args:
            search (str | None): Subcadena a buscar en `file_path` (nombre o carpeta),
                insensible a mayusculas/tildes. `None` o cadena vacia cuenta todas.

        Returns:
            int: Numero de entradas que coinciden.

        Example:
            >>> total = await cache.count_entries("informe")
        """
        query = "SELECT COUNT(*) FROM cache_entries"
        params: tuple[str, ...] = ()
        if search:
            query += " WHERE py_lower(file_path) LIKE py_lower(?) ESCAPE '\\'"
            params = (_like_pattern(search),)
        async with self._connection.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def load_cache_page(self, limit: int, offset: int, search: str | None = None) -> list[CacheEntry]:
        """Lee una pagina de `cache_entries`, ordenada por `file_path` para paginacion estable.

        Pensado para la vista web del Cache Viewer (listas largas); no sustituye a
        `load_cache()`, que sigue siendo la fuente completa para `get_changes()` y
        la exportacion ZIP.

        Args:
            limit (int): Numero maximo de entradas a devolver.
            offset (int): Entradas a saltar desde el principio del orden.
            search (str | None): Subcadena a buscar en `file_path`, insensible a
                mayusculas/tildes. `None` o cadena vacia no filtra.

        Returns:
            list[CacheEntry]: Entradas de la pagina solicitada, ordenadas por `file_path`.

        Example:
            >>> page = await cache.load_cache_page(limit=50, offset=0)
        """
        query = "SELECT file_path, sha256_hash, timestamp, status, conversion_status FROM cache_entries"
        params: list[object] = []
        if search:
            query += " WHERE py_lower(file_path) LIKE py_lower(?) ESCAPE '\\'"
            params.append(_like_pattern(search))
        query += " ORDER BY file_path LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        entries: list[CacheEntry] = []
        async with self._connection.execute(query, params) as cursor:
            async for file_path, sha256_hash, timestamp, status, conversion_status in cursor:
                entries.append(
                    CacheEntry(
                        file_path=file_path,
                        sha256_hash=sha256_hash,
                        timestamp=timestamp,
                        status=DocumentStatus(status),
                        conversion_status=ConversionStatus(conversion_status) if conversion_status else None,
                    )
                )
        return entries

    async def compute_hash(self, file_path: str) -> str:
        """Delega en `utils.hash_utils.hash_file()` — no reimplementa el hashing."""
        return await hash_file(file_path)

    def get_changes(
        self,
        cache: dict[str, CacheEntry],
        current_docs: list[DocumentMetadata],
    ) -> tuple[list[str], list[str], list[str]]:
        """Compara `current_docs` contra `cache` y clasifica cada ruta.

        Sincrono a proposito: solo compara datos ya cargados en memoria
        (sin I/O), igual que `FolderValidator.validate_folder_set` y
        `DeduplicationManager.find_duplicates`.

        Returns:
            Tupla (new_files, modified_files, unchanged_files) con rutas absolutas.
        """
        new_files: list[str] = []
        modified_files: list[str] = []
        unchanged_files: list[str] = []

        for doc in current_docs:
            cached = cache.get(doc.full_path)
            if cached is None:
                new_files.append(doc.full_path)
            elif cached.sha256_hash != doc.sha256_hash:
                modified_files.append(doc.full_path)
            else:
                unchanged_files.append(doc.full_path)

        self.logger.info(f"Cambios detectados: {len(new_files)} nuevos, {len(modified_files)} modificados, {len(unchanged_files)} sin cambios")
        return new_files, modified_files, unchanged_files

    async def save_entries(self, entries: list[CacheEntry]) -> None:
        """Upsert transaccional de `entries` en `cache.db`."""
        if not entries:
            return
        rows = [
            (
                entry.file_path,
                entry.sha256_hash,
                entry.timestamp,
                entry.status.value,
                entry.conversion_status.value if entry.conversion_status else None,
            )
            for entry in entries
        ]
        await self._connection.executemany(_UPSERT, rows)
        await self._connection.commit()
        self.logger.info(f"Cache actualizado: {len(entries)} entradas")


__all__ = ["CacheManager"]
