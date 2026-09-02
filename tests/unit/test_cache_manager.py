"""Tests unitarios de CacheManager (REQ-006)."""

import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.exceptions import CacheError
from doc_organize.core.models import CacheEntry, DocumentMetadata, DocumentStatus


def _entry(file_path: str, sha256_hash: str, timestamp: float = 1.0, error_message: str | None = None) -> CacheEntry:
    return CacheEntry(
        file_path=file_path,
        sha256_hash=sha256_hash,
        timestamp=timestamp,
        status=DocumentStatus.NEW,
        conversion_status=None,
        error_message=error_message,
    )


def _doc(file_path: str, sha256_hash: str) -> DocumentMetadata:
    return DocumentMetadata(
        full_path=file_path,
        display_name=file_path.rsplit("/", 1)[-1],
        extension="pdf",
        size_bytes=10,
        modified_time=1.0,
        sha256_hash=sha256_hash,
    )


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a", error_message="Documento cifrado")])
        loaded = await cache.load_cache()

    assert "/repo/a.pdf" in loaded
    assert loaded["/repo/a.pdf"].sha256_hash == "hash-a"
    assert loaded["/repo/a.pdf"].error_message == "Documento cifrado"


@pytest.mark.asyncio
async def test_save_entries_upserts_existing_row(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a", timestamp=1.0)])
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a-modified", timestamp=2.0)])
        loaded = await cache.load_cache()

    assert len(loaded) == 1
    assert loaded["/repo/a.pdf"].sha256_hash == "hash-a-modified"


@pytest.mark.asyncio
async def test_get_changes_classifies_new_modified_unchanged(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries(
            [
                _entry("/repo/unchanged.pdf", "hash-same"),
                _entry("/repo/modified.pdf", "hash-old"),
            ]
        )
        existing = await cache.load_cache()

        current_docs = [
            _doc("/repo/unchanged.pdf", "hash-same"),
            _doc("/repo/modified.pdf", "hash-new"),
            _doc("/repo/new.pdf", "hash-brand-new"),
        ]
        new_files, modified_files, unchanged_files = cache.get_changes(existing, current_docs)

    assert new_files == ["/repo/new.pdf"]
    assert modified_files == ["/repo/modified.pdf"]
    assert unchanged_files == ["/repo/unchanged.pdf"]


@pytest.mark.asyncio
async def test_compute_hash_matches_hash_utils(tmp_path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"same-source-of-truth")

    from doc_organize.utils.hash_utils import hash_file

    async with CacheManager(tmp_path / "cache.db") as cache:
        via_cache_manager = await cache.compute_hash(str(sample))
    via_hash_utils = await hash_file(str(sample))

    assert via_cache_manager == via_hash_utils


@pytest.mark.asyncio
async def test_clear_removes_all_entries(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a"), _entry("/repo/b.pdf", "hash-b")])
        await cache.clear()
        loaded = await cache.load_cache()

    assert loaded == {}


@pytest.mark.asyncio
async def test_clear_on_empty_cache_is_a_no_op(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.clear()
        loaded = await cache.load_cache()

    assert loaded == {}


@pytest.mark.asyncio
async def test_migrate_adds_error_message_column_to_legacy_db(tmp_path) -> None:
    db_path = tmp_path / "cache.db"

    import aiosqlite

    async with aiosqlite.connect(db_path) as legacy_conn:
        await legacy_conn.execute(
            """
            CREATE TABLE cache_entries (
                file_path TEXT PRIMARY KEY,
                sha256_hash TEXT NOT NULL,
                timestamp REAL NOT NULL,
                status TEXT NOT NULL,
                conversion_status TEXT
            )
            """
        )
        await legacy_conn.execute(
            "INSERT INTO cache_entries VALUES (?, ?, ?, ?, ?)",
            ("/repo/legacy.pdf", "hash-legacy", 1.0, "new", "error"),
        )
        await legacy_conn.commit()

    async with CacheManager(db_path) as cache:
        loaded = await cache.load_cache()

    assert loaded["/repo/legacy.pdf"].error_message is None


@pytest.mark.asyncio
async def test_using_outside_context_manager_raises() -> None:
    cache = CacheManager("unused.db")
    with pytest.raises(CacheError):
        await cache.load_cache()


@pytest.mark.asyncio
async def test_load_cache_page_orders_by_file_path_and_respects_limit_offset(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries(
            [
                _entry("/repo/c.pdf", "hash-c"),
                _entry("/repo/a.pdf", "hash-a"),
                _entry("/repo/b.pdf", "hash-b"),
            ]
        )
        first_page = await cache.load_cache_page(limit=2, offset=0)
        second_page = await cache.load_cache_page(limit=2, offset=2)

    assert [entry.file_path for entry in first_page] == ["/repo/a.pdf", "/repo/b.pdf"]
    assert [entry.file_path for entry in second_page] == ["/repo/c.pdf"]


@pytest.mark.asyncio
async def test_count_entries_without_search_counts_all(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a"), _entry("/repo/b.pdf", "hash-b")])
        total = await cache.count_entries()

    assert total == 2


@pytest.mark.asyncio
async def test_search_filters_by_file_path_case_and_accent_insensitive(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries(
            [
                _entry("/repo/Café.pdf", "hash-cafe"),
                _entry("/repo/other.pdf", "hash-other"),
            ]
        )
        total = await cache.count_entries("CAFÉ")
        page = await cache.load_cache_page(limit=10, offset=0, search="CAFÉ")

    assert total == 1
    assert [entry.file_path for entry in page] == ["/repo/Café.pdf"]


@pytest.mark.asyncio
async def test_search_with_like_special_characters_is_treated_literally(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries(
            [
                _entry("/repo/100%_done.pdf", "hash-percent"),
                _entry("/repo/100Xdone.pdf", "hash-x"),
            ]
        )
        total = await cache.count_entries("100%_done")

    # "%" y "_" deben tratarse como literales (escapados), no como comodines de LIKE:
    # de lo contrario "100%_done" tambien encontraria "100Xdone".
    assert total == 1
