"""Tests unitarios de CacheManager (REQ-006)."""

import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.exceptions import CacheError
from doc_organize.core.models import CacheEntry, DocumentMetadata, DocumentStatus


def _entry(file_path: str, sha256_hash: str, timestamp: float = 1.0) -> CacheEntry:
    return CacheEntry(
        file_path=file_path,
        sha256_hash=sha256_hash,
        timestamp=timestamp,
        status=DocumentStatus.NEW,
        conversion_status=None,
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
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a")])
        loaded = await cache.load_cache()

    assert "/repo/a.pdf" in loaded
    assert loaded["/repo/a.pdf"].sha256_hash == "hash-a"


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
async def test_using_outside_context_manager_raises() -> None:
    cache = CacheManager("unused.db")
    with pytest.raises(CacheError):
        await cache.load_cache()
