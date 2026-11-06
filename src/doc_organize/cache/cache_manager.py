"""
Cache transaccional (SQLite + WAL) de hashes de documentos (REQ-006).
"""

from pathlib import Path
from typing import Literal, Self, get_args

import aiosqlite

from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.exceptions import CacheError, CacheNotFoundError
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentMetadata, DocumentStatus
from doc_organize.utils.hash_utils import hash_file
from doc_organize.utils.logging import get_logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    file_path TEXT PRIMARY KEY,
    sha256_hash TEXT NOT NULL,
    timestamp REAL NOT NULL,
    status TEXT NOT NULL,
    conversion_status TEXT,
    error_message TEXT,
    error_retry_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER
)
"""

_UPSERT = """
INSERT INTO cache_entries (file_path, sha256_hash, timestamp, status, conversion_status, error_message, error_retry_count, size_bytes)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(file_path) DO UPDATE SET
    sha256_hash=excluded.sha256_hash,
    timestamp=excluded.timestamp,
    status=excluded.status,
    conversion_status=excluded.conversion_status,
    error_message=excluded.error_message,
    error_retry_count=excluded.error_retry_count,
    size_bytes=excluded.size_bytes
"""


def _py_lower(value: str | None) -> str | None:
    """Funcion SQL `py_lower`: plegado a minusculas Unicode-aware (registrada por conexion)."""
    return value.lower() if value is not None else None


_COLUMNS = ("file_path", "sha256_hash", "timestamp", "status", "conversion_status", "error_message", "error_retry_count")

CacheOrderBy = Literal["file_path", "timestamp", "conversion_status", "status", "size_bytes", "error_retry_count"]
"""Columnas por las que `CacheManager.load_cache_page` puede ordenar (G40, 1.2.0)."""

_ORDER_BY_COLUMNS: frozenset[str] = frozenset(get_args(CacheOrderBy))


def _py_relpath(file_path: str | None, root: str | None) -> str | None:
    """Funcion SQL `py_relpath`: parte de `file_path` bajo `root` (sin separador inicial) o `NULL` si no cuelga de ella.

    Acepta `/` y `\\` como separador para que una caché escrita en Windows se filtre igual desde otro sistema.
    """
    if file_path is None or root is None:
        return None
    if not file_path.startswith(root):
        return None
    rest = file_path[len(root) :]
    if root.endswith(("/", "\\")):
        return rest
    if rest[:1] in ("/", "\\"):
        return rest[1:]
    return None


def _normalize_root(relative_to: str | Path) -> str:
    """Raiz resuelta como la guarda el escaneo (`DocumentScanner` usa rutas `resolve()`)."""
    return str(Path(relative_to).expanduser().resolve())


def _like_pattern(search: str) -> str:
    """Envuelve `search` en comodines `%...%` escapando `\\`, `%` y `_` (literales de LIKE)."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class CacheManager:
    """Gestiona el cache transaccional de hashes en `cache.db` (SQLite, WAL).

    Unica fuente de verdad de hashing: `compute_hash()` delega en
    `utils.hash_utils.hash_file()`, nunca reimplementa SHA-256. El modo WAL
    permite lecturas concurrentes mientras otro proceso escribe.

    Con `read_only=True` (L-10e, G21) abre la caché con la URI `mode=ro`: no
    cambia el modo de diario, no crea la tabla ni migra columnas, y
    `save_entries`/`clear` lanzan `CacheError`. Pensado para leer la caché que
    otro proceso escribe (p. ej. la API de doc_organize_web mientras su worker escanea).

    Attributes:
        db_path (Path): Ruta al archivo SQLite de cache.
        read_only (bool): Si la caché se abre en solo lectura.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     db_path = Path(tempfile.mkdtemp()) / "cache.db"
        ...     async with CacheManager(db_path) as cache:
        ...         entries = await cache.load_cache()
        ...     return entries
        >>> asyncio.run(main())
        {}
    """

    def __init__(self, db_path: str | Path = DEFAULT_CACHE_DB_NAME, *, read_only: bool = False) -> None:
        self.db_path = Path(db_path)
        self.read_only = read_only
        self.logger = get_logger(__name__)
        self._conn: aiosqlite.Connection | None = None
        self._has_size_column = True

    async def __aenter__(self) -> Self:
        """Abre la conexion (y, en escritura, prepara WAL, tabla y columnas).

        Raises:
            CacheNotFoundError: `read_only=True` y `db_path` no existe (no se crea).
            CacheError: `read_only=True` y la caché no tiene la tabla o las columnas
                actuales (abrela una vez en escritura para migrarla).
        """
        if self.read_only:
            await self._connect_read_only()
        else:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute(_SCHEMA)
            await self._conn.commit()
            await self._migrate_schema()
        # Ordenaciones en memoria (G40): con el valor por defecto SQLite vuelca a ficheros temporales en disco al ordenar
        # una página con offset alto por una columna sin índice (~1 s con 100 000 entradas; ~0,1 s así). Solo afecta a
        # esta conexión: no cambia el fichero, así que vale también en solo lectura.
        await self._connection.execute("PRAGMA temp_store=MEMORY")
        # SQLite LIKE/LOWER() solo pliegan mayusculas para ASCII: sin esto, buscar
        # "cafe" no encontraria "CAFE" en nombres de archivo en espanol con tildes.
        await self._connection.create_function("py_lower", 1, _py_lower, deterministic=True)
        await self._connection.create_function("py_relpath", 2, _py_relpath, deterministic=True)
        return self

    async def _connect_read_only(self) -> None:
        """Conexion `mode=ro` sin PRAGMA, CREATE ni ALTER; comprueba que el esquema es el actual (G21)."""
        if not self.db_path.is_file():
            raise CacheNotFoundError(f"No existe la caché '{self.db_path}'.")
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        self._conn = await aiosqlite.connect(uri, uri=True)
        try:
            cursor = await self._conn.execute("PRAGMA table_info(cache_entries)")
            columns = {row[1] for row in await cursor.fetchall()}
        except Exception as exc:  # p. ej. sqlite3.DatabaseError si el fichero no es una base SQLite
            await self.__aexit__()
            raise CacheError(f"No se pudo leer la caché '{self.db_path}': {exc}") from exc
        self._has_size_column = "size_bytes" in columns
        missing = set(_COLUMNS) - columns
        if missing:
            await self.__aexit__()
            raise CacheError(
                f"La caché '{self.db_path}' no tiene el esquema actual (faltan {', '.join(sorted(missing))}): "
                "ábrela una vez sin `read_only` para migrarla."
            )

    async def _migrate_schema(self) -> None:
        """Anade columnas nuevas a `cache_entries` si faltan (bases de datos creadas
        antes de esta revision). SQLite no soporta `ADD COLUMN IF NOT EXISTS`, de ahi
        la comprobacion manual via `PRAGMA table_info` — migración aditiva
        de columnas."""
        cursor = await self._connection.execute("PRAGMA table_info(cache_entries)")
        columns = {row[1] for row in await cursor.fetchall()}

        altered = False
        if "error_message" not in columns:
            await self._connection.execute("ALTER TABLE cache_entries ADD COLUMN error_message TEXT")
            altered = True
        if "error_retry_count" not in columns:
            await self._connection.execute("ALTER TABLE cache_entries ADD COLUMN error_retry_count INTEGER NOT NULL DEFAULT 0")
            altered = True
        if "size_bytes" not in columns:
            await self._connection.execute("ALTER TABLE cache_entries ADD COLUMN size_bytes INTEGER")
            altered = True
        if altered:
            await self._connection.commit()

    async def __aexit__(self, *exc_info: object) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise CacheError("CacheManager debe usarse como context manager async ('async with').")
        return self._conn

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise CacheError(f"La caché '{self.db_path}' está abierta en solo lectura.")

    @staticmethod
    def _build_filters(
        search: str | None, relative_to: str | Path | None, conversion_status: ConversionStatus | str | None
    ) -> tuple[str, list[object]]:
        """Clausula `WHERE` (o cadena vacia) y parametros comunes a `count_entries` y `load_cache_page`."""
        conditions: list[str] = []
        params: list[object] = []
        if relative_to is not None:
            params.append(_normalize_root(relative_to))
            conditions.append("py_relpath(file_path, ?) IS NOT NULL")
            if search:
                conditions.append("py_lower(py_relpath(file_path, ?)) LIKE py_lower(?) ESCAPE '\\'")
                params.extend([params[0], _like_pattern(search)])
        elif search:
            conditions.append("py_lower(file_path) LIKE py_lower(?) ESCAPE '\\'")
            params.append(_like_pattern(search))
        if conversion_status is not None:
            conditions.append("conversion_status = ?")
            params.append(ConversionStatus(conversion_status).value)
        return (" WHERE " + " AND ".join(conditions) if conditions else ""), params

    async def load_cache(self) -> dict[str, CacheEntry]:
        """Lee todas las entradas de `cache.db`."""
        cache: dict[str, CacheEntry] = {}
        query = f"SELECT {self._select_columns()} FROM cache_entries"
        async with self._connection.execute(query) as cursor:
            async for row in cursor:
                entry = self._row_to_entry(row)
                cache[entry.file_path] = entry
        return cache

    def _select_columns(self) -> str:
        """Columnas del `SELECT`; `size_bytes` como `NULL` en una caché antigua abierta en solo lectura (G25)."""
        size_column = "size_bytes" if self._has_size_column else "NULL"
        return ", ".join((*_COLUMNS, size_column))

    @staticmethod
    def _row_to_entry(row: tuple[object, ...] | aiosqlite.Row) -> CacheEntry:
        file_path, sha256_hash, timestamp, status, conversion_value, error_message, error_retry_count, size_bytes = row
        return CacheEntry(
            file_path=file_path,
            sha256_hash=sha256_hash,
            timestamp=timestamp,
            status=DocumentStatus(status),
            conversion_status=ConversionStatus(conversion_value) if conversion_value else None,
            error_message=error_message,
            error_retry_count=error_retry_count,
            size_bytes=size_bytes,
        )

    async def count_entries(
        self,
        search: str | None = None,
        *,
        relative_to: str | Path | None = None,
        conversion_status: ConversionStatus | str | None = None,
    ) -> int:
        """Cuenta entradas de `cache_entries`, opcionalmente filtradas.

        Args:
            search (str | None): Subcadena a buscar en `file_path` (nombre o carpeta),
                insensible a mayusculas/tildes. `None` o cadena vacia cuenta todas.
            relative_to (str | Path | None): Raiz escaneada (G22): solo cuenta las
                entradas que cuelgan de ella y `search` se aplica a la ruta relativa
                a esa raiz (sin el prefijo del montaje).
            conversion_status (ConversionStatus | str | None): Solo las entradas con
                ese estado de conversion (p. ej. `ConversionStatus.ERROR`).

        Returns:
            int: Numero de entradas que coinciden.

        Example:
            >>> import asyncio, tempfile
            >>> from pathlib import Path
            >>> async def main():
            ...     db_path = Path(tempfile.mkdtemp()) / "cache.db"
            ...     async with CacheManager(db_path) as cache:
            ...         return await cache.count_entries("informe")
            >>> asyncio.run(main())
            0
        """
        where, params = self._build_filters(search, relative_to, conversion_status)
        query = "SELECT COUNT(*) FROM cache_entries" + where
        async with self._connection.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def load_cache_page(
        self,
        limit: int,
        offset: int,
        search: str | None = None,
        *,
        relative_to: str | Path | None = None,
        conversion_status: ConversionStatus | str | None = None,
        order_by: CacheOrderBy = "file_path",
        descending: bool = False,
    ) -> list[CacheEntry]:
        """Lee una pagina de `cache_entries`, ordenada por `file_path` (o por `order_by`) para paginacion estable.

        Pensado para listados paginados (listas largas); no sustituye a
        `load_cache()`, que sigue siendo la fuente completa para `get_changes()` y
        la exportacion ZIP.

        Args:
            limit (int): Numero maximo de entradas a devolver.
            offset (int): Entradas a saltar desde el principio del orden.
            search (str | None): Subcadena a buscar en `file_path`, insensible a
                mayusculas/tildes. `None` o cadena vacia no filtra.
            relative_to (str | Path | None): Igual que en `count_entries` (G22).
            conversion_status (ConversionStatus | str | None): Igual que en `count_entries`.
            order_by (CacheOrderBy): Columna de orden (G40, 1.2.0). Los empates se resuelven siempre por
                `file_path` ascendente, asi que el orden es total y el mismo en cualquier caché. `conversion_status` y
                `status` se ordenan por el texto de su valor (`"error"` < `"ocr_pending"` < `"success"`).
            descending (bool): Orden descendente de `order_by` (el desempate por `file_path` sigue ascendente). Los
                `NULL` (`size_bytes` de entradas anteriores a 1.1.0, `conversion_status` sin valor) van al final en
                los dos sentidos.

        Returns:
            list[CacheEntry]: Entradas de la pagina solicitada, en ese orden.

        Raises:
            ValueError: Si `order_by` no es una de las columnas de `CacheOrderBy`.

        Example:
            >>> import asyncio, tempfile
            >>> from pathlib import Path
            >>> async def main():
            ...     db_path = Path(tempfile.mkdtemp()) / "cache.db"
            ...     async with CacheManager(db_path) as cache:
            ...         return await cache.load_cache_page(limit=50, offset=0, order_by="size_bytes", descending=True)
            >>> asyncio.run(main())
            []
        """
        order_clause = self._order_clause(order_by, descending)
        where, params = self._build_filters(search, relative_to, conversion_status)
        if order_by == "file_path":
            query = f"SELECT {self._select_columns()} FROM cache_entries{where} ORDER BY {order_clause} LIMIT ? OFFSET ?"
        else:
            # Se ordenan solo las claves y luego se leen las filas de la página: ordenar filas completas cuesta el doble.
            query = (
                f"SELECT {self._select_columns()} FROM cache_entries WHERE rowid IN "
                f"(SELECT rowid FROM cache_entries{where} ORDER BY {order_clause} LIMIT ? OFFSET ?) ORDER BY {order_clause}"
            )
        params.extend([limit, offset])

        entries: list[CacheEntry] = []
        async with self._connection.execute(query, params) as cursor:
            async for row in cursor:
                entries.append(self._row_to_entry(row))
        return entries

    def _order_clause(self, order_by: str, descending: bool) -> str:
        """`ORDER BY` de `load_cache_page`; solo con nombres de `CacheOrderBy`, nunca con texto del llamador (G40)."""
        if order_by not in _ORDER_BY_COLUMNS:
            raise ValueError(f"order_by no válido: {order_by!r}; usa uno de {', '.join(get_args(CacheOrderBy))}.")
        direction = "DESC" if descending else "ASC"
        if order_by == "file_path":
            return f"file_path {direction}"
        column = "NULL" if order_by == "size_bytes" and not self._has_size_column else order_by
        return f"{column} IS NULL, {column} {direction}, file_path ASC"

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

    async def clear(self) -> None:
        """Vacia `cache_entries` por completo — usado por "forzar rescan".

        A diferencia de `save_entries()`, no es un upsert: borra toda fila
        existente para que la proxima comparacion (`get_changes()`) trate
        todos los documentos como nuevos, sin depender de ningun hash previo.
        """
        self._ensure_writable()
        await self._connection.execute("DELETE FROM cache_entries")
        await self._connection.commit()
        self.logger.info("Cache vaciada (forzar rescan)")

    async def save_entries(self, entries: list[CacheEntry]) -> None:
        """Upsert transaccional de `entries` en `cache.db`."""
        self._ensure_writable()
        if not entries:
            return
        rows = [
            (
                entry.file_path,
                entry.sha256_hash,
                entry.timestamp,
                entry.status.value,
                entry.conversion_status.value if entry.conversion_status else None,
                entry.error_message,
                entry.error_retry_count,
                entry.size_bytes,
            )
            for entry in entries
        ]
        await self._connection.executemany(_UPSERT, rows)
        await self._connection.commit()
        self.logger.info(f"Cache actualizado: {len(entries)} entradas")


__all__ = ["CacheManager", "CacheOrderBy"]
