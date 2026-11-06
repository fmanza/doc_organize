"""Orden de las páginas de la caché por más columnas que la ruta (G40 / L-18, 1.2.0)."""

import sqlite3
import time

from collections.abc import AsyncIterator
from pathlib import Path
from typing import get_args

import pytest
import pytest_asyncio

from doc_organize.cache import CacheManager, CacheOrderBy
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus

_HASH = "ab" * 32


def _entry(
    name: str,
    *,
    timestamp: float = 1.0,
    status: DocumentStatus = DocumentStatus.NEW,
    conversion_status: ConversionStatus | None = None,
    size_bytes: int | None = None,
    error_retry_count: int = 0,
) -> CacheEntry:
    return CacheEntry(
        file_path=f"/repo/{name}",
        sha256_hash=_HASH,
        timestamp=timestamp,
        status=status,
        conversion_status=conversion_status,
        error_retry_count=error_retry_count,
        size_bytes=size_bytes,
    )


# Valores con empates y NULL en cada columna; el orden de inserción no coincide con ninguno de los esperados.
_ENTRIES = [
    _entry("e.pdf", timestamp=3.0, status=DocumentStatus.MODIFIED, conversion_status=ConversionStatus.SUCCESS, size_bytes=500, error_retry_count=1),
    _entry("a.pdf", timestamp=2.0, status=DocumentStatus.UNCHANGED, conversion_status=None, size_bytes=None, error_retry_count=0),
    _entry("d.pdf", timestamp=1.0, status=DocumentStatus.NEW, conversion_status=ConversionStatus.ERROR, size_bytes=100, error_retry_count=2),
    _entry("b.pdf", timestamp=3.0, status=DocumentStatus.NEW, conversion_status=ConversionStatus.SUCCESS, size_bytes=100, error_retry_count=0),
    _entry(
        "c.pdf", timestamp=2.0, status=DocumentStatus.MODIFIED, conversion_status=ConversionStatus.OCR_PENDING, size_bytes=None, error_retry_count=1
    ),
]

# Esperado: valor ascendente/descendente, NULL al final y desempate por ruta ascendente.
_EXPECTED: dict[str, tuple[list[str], list[str]]] = {
    "file_path": (["a", "b", "c", "d", "e"], ["e", "d", "c", "b", "a"]),
    "timestamp": (["d", "a", "c", "b", "e"], ["b", "e", "a", "c", "d"]),
    "status": (["c", "e", "b", "d", "a"], ["a", "b", "d", "c", "e"]),  # "modified" < "new" < "unchanged"
    "conversion_status": (["d", "c", "b", "e", "a"], ["b", "e", "c", "d", "a"]),  # "error" < "ocr_pending" < "success"
    "size_bytes": (["b", "d", "e", "a", "c"], ["e", "b", "d", "a", "c"]),
    "error_retry_count": (["a", "b", "c", "e", "d"], ["d", "c", "e", "a", "b"]),
}


def _names(entries: list[CacheEntry]) -> list[str]:
    return [Path(entry.file_path).stem for entry in entries]


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> AsyncIterator[CacheManager]:
    async with CacheManager(tmp_path / "cache.db") as manager:
        await manager.save_entries(_ENTRIES)
        yield manager


def test_expected_covers_every_order_by_column() -> None:
    assert set(_EXPECTED) == set(get_args(CacheOrderBy))


@pytest.mark.asyncio
@pytest.mark.parametrize("order_by", list(_EXPECTED))
@pytest.mark.parametrize("descending", [False, True])
async def test_load_cache_page_orders_by_column_with_nulls_last_and_path_tiebreak(cache: CacheManager, order_by: str, descending: bool) -> None:
    page = await cache.load_cache_page(limit=10, offset=0, order_by=order_by, descending=descending)  # type: ignore[arg-type]

    assert _names(page) == _EXPECTED[order_by][int(descending)]


@pytest.mark.asyncio
@pytest.mark.parametrize("order_by", list(_EXPECTED))
@pytest.mark.parametrize("descending", [False, True])
async def test_pages_concatenate_to_the_full_order(cache: CacheManager, order_by: str, descending: bool) -> None:
    pages = [await cache.load_cache_page(limit=2, offset=offset, order_by=order_by, descending=descending) for offset in (0, 2, 4)]  # type: ignore[arg-type]

    assert [name for page in pages for name in _names(page)] == _EXPECTED[order_by][int(descending)]


@pytest.mark.asyncio
async def test_default_order_is_unchanged(cache: CacheManager) -> None:
    assert _names(await cache.load_cache_page(limit=10, offset=0)) == ["a", "b", "c", "d", "e"]


@pytest.mark.asyncio
async def test_order_by_combines_with_search_and_conversion_status(cache: CacheManager) -> None:
    success = await cache.load_cache_page(10, 0, conversion_status=ConversionStatus.SUCCESS, order_by="size_bytes", descending=True)
    searched = await cache.load_cache_page(10, 0, "PDF", order_by="timestamp", descending=True)
    narrowed = await cache.load_cache_page(10, 0, "c.p", order_by="timestamp")

    assert _names(success) == ["e", "b"]
    assert _names(searched) == ["b", "e", "a", "c", "d"]
    assert _names(narrowed) == ["c"]
    assert await cache.count_entries(conversion_status=ConversionStatus.SUCCESS) == 2


@pytest.mark.asyncio
async def test_order_by_combines_with_relative_to(tmp_path: Path) -> None:
    root = tmp_path / "raiz"
    inside = [
        CacheEntry(file_path=str(root / name), sha256_hash=_HASH, timestamp=1.0, status=DocumentStatus.NEW, size_bytes=size)
        for name, size in (("x.pdf", 10), ("y.pdf", 30), ("z.pdf", 20))
    ]
    outside = CacheEntry(file_path=str(tmp_path / "otra" / "w.pdf"), sha256_hash=_HASH, timestamp=1.0, status=DocumentStatus.NEW, size_bytes=99)
    async with CacheManager(tmp_path / "cache.db") as manager:
        await manager.save_entries([*inside, outside])
        page = await manager.load_cache_page(10, 0, relative_to=root, order_by="size_bytes", descending=True)

    assert _names(page) == ["y", "z", "x"]


@pytest.mark.asyncio
@pytest.mark.parametrize("order_by", ["name", "file_path; DROP TABLE cache_entries", "FILE_PATH", ""])
async def test_invalid_order_by_raises_value_error(cache: CacheManager, order_by: str) -> None:
    with pytest.raises(ValueError, match="order_by"):
        await cache.load_cache_page(10, 0, order_by=order_by)  # type: ignore[arg-type]

    assert await cache.count_entries() == len(_ENTRIES)


def _pre_1_1_cache(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE cache_entries (file_path TEXT PRIMARY KEY, sha256_hash TEXT NOT NULL, timestamp REAL NOT NULL, "
            "status TEXT NOT NULL, conversion_status TEXT, error_message TEXT, error_retry_count INTEGER NOT NULL DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO cache_entries VALUES (?, ?, ?, 'new', 'success', NULL, 0)",
            [("/repo/b.pdf", _HASH, 1.0), ("/repo/a.pdf", _HASH, 2.0), ("/repo/c.pdf", _HASH, 2.0)],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("read_only", [True, False])
async def test_pre_1_1_cache_orders_without_size_bytes(tmp_path: Path, read_only: bool) -> None:
    db = tmp_path / "cache.db"
    _pre_1_1_cache(db)

    async with CacheManager(db, read_only=read_only) as manager:
        by_size = await manager.load_cache_page(10, 0, order_by="size_bytes", descending=True)
        by_time = await manager.load_cache_page(10, 0, order_by="timestamp", descending=True)

    assert _names(by_size) == ["a", "b", "c"]  # todo NULL: queda el desempate por ruta
    assert [entry.size_bytes for entry in by_size] == [None, None, None]
    assert _names(by_time) == ["a", "c", "b"]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_high_offset_page_is_fast_with_100k_entries(tmp_path: Path) -> None:
    """Petición de doc_organize_web: < 300 ms por página con 100 000 entradas en disco local (margen x2 para CI)."""
    count = 100_000
    statuses = [ConversionStatus.SUCCESS, ConversionStatus.ERROR, ConversionStatus.OCR_PENDING, None]
    entries = [
        CacheEntry(
            file_path=f"/datos/proyecto/carpeta_{i % 300:03d}/sub_{i % 17}/documento_{i:06d}_informe.pdf",
            sha256_hash=_HASH,
            timestamp=float((i * 7919) % 100_003),
            status=list(DocumentStatus)[i % len(DocumentStatus)],
            conversion_status=statuses[i % 4],
            error_retry_count=i % 3,
            size_bytes=None if i % 5 == 0 else (i * 104_729) % 10_000_000,
        )
        for i in range(count)
    ]
    async with CacheManager(tmp_path / "cache.db") as manager:
        await manager.save_entries(entries)
        for order_by in get_args(CacheOrderBy):
            for descending in (False, True):
                start = time.perf_counter()
                page = await manager.load_cache_page(50, count - 60, order_by=order_by, descending=descending)
                elapsed = time.perf_counter() - start
                assert len(page) == 50
                assert elapsed < 0.6, f"{order_by} descending={descending}: {elapsed * 1000:.0f} ms"
