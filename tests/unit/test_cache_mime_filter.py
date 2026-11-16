"""Filtro por tipo MIME y lista de tipos de la caché (G43, 1.6.0)."""

import sqlite3

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from doc_organize.cache import CacheManager
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus

_HASH = "ab" * 32
_PDF, _DOCX, _TXT = "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"


def _entry(path: str, mime_type: str | None, conversion_status: ConversionStatus | None = ConversionStatus.SUCCESS) -> CacheEntry:
    return CacheEntry(
        file_path=path, sha256_hash=_HASH, timestamp=1.0, status=DocumentStatus.NEW, conversion_status=conversion_status, mime_type=mime_type
    )


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> AsyncIterator[CacheManager]:
    root = tmp_path / "raiz"
    entries = [
        _entry(str(root / "informe.pdf"), _PDF),
        _entry(str(root / "acta.pdf"), _PDF, ConversionStatus.ERROR),
        _entry(str(root / "sub" / "plan.docx"), _DOCX),
        _entry(str(root / "notas.txt"), _TXT),
        _entry(str(root / "antiguo.pdf"), None),  # escaneado antes de 1.5.0
        _entry(str(tmp_path / "otra" / "fuera.pdf"), _PDF),
    ]
    async with CacheManager(tmp_path / "cache.db") as manager:
        await manager.save_entries(entries)
        yield manager


def _names(entries: list[CacheEntry]) -> list[str]:
    return [Path(entry.file_path).name for entry in entries]


@pytest.mark.asyncio
async def test_filters_by_one_mime_type(cache: CacheManager) -> None:
    page = await cache.load_cache_page(10, 0, mime_type=_PDF)

    assert _names(page) == ["fuera.pdf", "acta.pdf", "informe.pdf"]  # por ruta: .../otra/ antes que .../raiz/
    assert await cache.count_entries(mime_type=_PDF) == 3


@pytest.mark.asyncio
async def test_filters_by_several_mime_types(cache: CacheManager) -> None:
    page = await cache.load_cache_page(10, 0, mime_type=[_DOCX, _TXT])

    assert sorted(_names(page)) == ["notas.txt", "plan.docx"]
    assert await cache.count_entries(mime_type=(_DOCX, _TXT)) == 2
    assert await cache.count_entries(mime_type=[_PDF, _PDF, _PDF]) == 3  # repetidos: un solo parámetro


@pytest.mark.asyncio
@pytest.mark.parametrize("no_filter", [None, [], ()])
async def test_none_or_empty_does_not_filter(cache: CacheManager, no_filter: list[str] | None) -> None:
    assert await cache.count_entries(mime_type=no_filter) == 6


@pytest.mark.asyncio
async def test_combines_with_the_other_filters_and_order(cache: CacheManager, tmp_path: Path) -> None:
    root = tmp_path / "raiz"

    page = await cache.load_cache_page(10, 0, "a", relative_to=root, mime_type=_PDF, order_by="file_path", descending=True)
    count = await cache.count_entries("a", relative_to=root, conversion_status=ConversionStatus.SUCCESS, mime_type=[_PDF, _DOCX])

    assert _names(page) == ["acta.pdf"]  # "informe.pdf" no contiene "a"; "fuera.pdf" está fuera de la raíz
    assert count == 1  # plan.docx


@pytest.mark.asyncio
async def test_unknown_or_hostile_values_match_nothing(cache: CacheManager) -> None:
    assert await cache.count_entries(mime_type="application/pdf' OR 1=1 --") == 0
    assert await cache.count_entries(mime_type="APPLICATION/PDF") == 0  # igualdad exacta
    assert await cache.count_entries() == 6


@pytest.mark.asyncio
async def test_list_mime_types_counts_each_type(cache: CacheManager, tmp_path: Path) -> None:
    assert await cache.list_mime_types() == [(_PDF, 3), (_DOCX, 1), (_TXT, 1)]
    assert await cache.list_mime_types(relative_to=tmp_path / "raiz") == [(_PDF, 2), (_DOCX, 1), (_TXT, 1)]
    assert await cache.list_mime_types(conversion_status=ConversionStatus.ERROR) == [(_PDF, 1)]
    assert await cache.list_mime_types("plan") == [(_DOCX, 1)]


def _pre_1_5_cache(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE cache_entries (file_path TEXT PRIMARY KEY, sha256_hash TEXT NOT NULL, timestamp REAL NOT NULL, "
            "status TEXT NOT NULL, conversion_status TEXT, error_message TEXT, error_retry_count INTEGER NOT NULL DEFAULT 0, "
            "size_bytes INTEGER)"
        )
        conn.executemany(
            "INSERT INTO cache_entries VALUES (?, ?, 1.0, 'new', 'success', NULL, 0, 10)",
            [("/repo/b.pdf", _HASH), ("/repo/a.pdf", _HASH)],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("read_only", [True, False])
async def test_pre_1_5_cache_has_no_types(tmp_path: Path, read_only: bool) -> None:
    db = tmp_path / "cache.db"
    _pre_1_5_cache(db)

    async with CacheManager(db, read_only=read_only) as manager:
        assert await manager.list_mime_types() == []
        assert await manager.count_entries(mime_type=_PDF) == 0
        assert await manager.load_cache_page(10, 0, mime_type=_PDF) == []
        by_owner = await manager.load_cache_page(10, 0, order_by="owner_name", descending=True)
        by_created = await manager.load_cache_page(10, 0, order_by="created_time")

    assert _names(by_owner) == ["a.pdf", "b.pdf"]  # todo NULL: queda el desempate por ruta
    assert _names(by_created) == ["a.pdf", "b.pdf"]
