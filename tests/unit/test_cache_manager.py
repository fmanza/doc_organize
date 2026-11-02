"""Tests unitarios de CacheManager (REQ-006)."""

import sqlite3

from pathlib import Path

import pytest

from doc_organize.cache import CacheManager
from doc_organize.cache.cache_manager import _py_relpath
from doc_organize.core.exceptions import CacheError, CacheNotFoundError
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentMetadata, DocumentStatus


def _entry(
    file_path: str,
    sha256_hash: str,
    timestamp: float = 1.0,
    error_message: str | None = None,
    error_retry_count: int = 0,
) -> CacheEntry:
    return CacheEntry(
        file_path=file_path,
        sha256_hash=sha256_hash,
        timestamp=timestamp,
        status=DocumentStatus.NEW,
        conversion_status=None,
        error_message=error_message,
        error_retry_count=error_retry_count,
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
        await cache.save_entries([_entry("/repo/a.pdf", "hash-a", error_message="Documento cifrado", error_retry_count=2)])
        loaded = await cache.load_cache()

    assert "/repo/a.pdf" in loaded
    assert loaded["/repo/a.pdf"].sha256_hash == "hash-a"
    assert loaded["/repo/a.pdf"].error_message == "Documento cifrado"
    assert loaded["/repo/a.pdf"].error_retry_count == 2


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
        assert loaded["/repo/legacy.pdf"].error_retry_count == 0

        # Round-trip completo tras la migracion: las columnas anadidas por ALTER
        # TABLE deben aceptar escrituras normales, no solo lecturas.
        await cache.save_entries([_entry("/repo/legacy.pdf", "hash-legacy", error_message="fallo tras migrar", error_retry_count=1)])
        reloaded = await cache.load_cache()

    assert reloaded["/repo/legacy.pdf"].error_message == "fallo tras migrar"
    assert reloaded["/repo/legacy.pdf"].error_retry_count == 1


@pytest.mark.asyncio
async def test_migrate_adds_only_missing_column_when_partially_migrated(tmp_path) -> None:
    """DB de una revision intermedia: `error_message` ya existe (migracion previa)
    pero `error_retry_count` no. La migracion debe anadir solo la que falta, sin
    fallar con "duplicate column" al comprobar `error_message`."""
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
                conversion_status TEXT,
                error_message TEXT
            )
            """
        )
        await legacy_conn.execute(
            "INSERT INTO cache_entries VALUES (?, ?, ?, ?, ?, ?)",
            ("/repo/parcial.pdf", "hash-parcial", 1.0, "new", "error", "fallo previo"),
        )
        await legacy_conn.commit()

    async with CacheManager(db_path) as cache:
        loaded = await cache.load_cache()

    assert loaded["/repo/parcial.pdf"].error_message == "fallo previo"
    assert loaded["/repo/parcial.pdf"].error_retry_count == 0


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


# --- L-10e: solo lectura (G21) y filtros (G22) ---------------------------------------------------------------------------


def _status_entry(file_path: str, conversion_status: ConversionStatus | None) -> CacheEntry:
    return _entry(file_path, f"hash-{file_path}").model_copy(update={"conversion_status": conversion_status})


@pytest.mark.asyncio
async def test_read_only_missing_cache_raises_typed_error_and_creates_nothing(tmp_path) -> None:
    db_path = tmp_path / "cache.db"

    with pytest.raises(CacheNotFoundError):
        async with CacheManager(db_path, read_only=True):
            pass

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_read_only_reads_while_writer_is_open_and_rejects_writes(tmp_path) -> None:
    db_path = tmp_path / "Conversión ñ" / "cache.db"  # ruta con espacios y no ASCII (URI)
    db_path.parent.mkdir()
    async with CacheManager(db_path) as writer:
        await writer.save_entries([_entry("/repo/a.pdf", "hash-a")])
        async with CacheManager(db_path, read_only=True) as reader:
            assert set(await reader.load_cache()) == {"/repo/a.pdf"}
            await writer.save_entries([_entry("/repo/b.pdf", "hash-b")])
            assert await reader.count_entries() == 2  # ve lo que el escritor confirma
            with pytest.raises(CacheError, match="solo lectura"):
                await reader.save_entries([_entry("/repo/c.pdf", "hash-c")])
            with pytest.raises(CacheError, match="solo lectura"):
                await reader.clear()


@pytest.mark.asyncio
async def test_read_only_does_not_create_table_nor_migrate(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE cache_entries (file_path TEXT PRIMARY KEY, sha256_hash TEXT, timestamp REAL, status TEXT, conversion_status TEXT)")

    with pytest.raises(CacheError, match="error_message"):
        async with CacheManager(db_path, read_only=True):
            pass

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(cache_entries)")}
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert "error_message" not in columns
    assert journal_mode == "delete"


@pytest.mark.asyncio
async def test_filters_by_path_relative_to_root_and_by_status(tmp_path) -> None:
    root = tmp_path.resolve() / "mnt" / "datos"
    other = tmp_path.resolve() / "mnt" / "otros"
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries(
            [
                _status_entry(str(root / "Informes" / "a.pdf"), ConversionStatus.SUCCESS),
                _status_entry(str(root / "Informes" / "b.pdf"), ConversionStatus.ERROR),
                _status_entry(str(root / "c.pdf"), ConversionStatus.ERROR),
                _status_entry(str(other / "Informes" / "d.pdf"), ConversionStatus.ERROR),
            ]
        )

        assert await cache.count_entries("mnt") == 4  # sin raíz: la ruta absoluta, como antes
        assert await cache.count_entries("mnt", relative_to=root) == 0  # el prefijo del montaje no cuenta
        assert await cache.count_entries(relative_to=root) == 3
        assert await cache.count_entries("informes", relative_to=str(root)) == 2
        assert await cache.count_entries(conversion_status=ConversionStatus.ERROR) == 3
        assert await cache.count_entries("informes", relative_to=root, conversion_status="error") == 1
        page = await cache.load_cache_page(limit=10, offset=0, relative_to=root, conversion_status=ConversionStatus.ERROR)
        assert [Path(entry.file_path).name for entry in page] == ["b.pdf", "c.pdf"]
        second = await cache.load_cache_page(limit=1, offset=1, search="pdf", relative_to=root)
        assert [Path(entry.file_path).name for entry in second] == ["b.pdf"]


@pytest.mark.asyncio
async def test_filters_also_work_in_read_only_mode(tmp_path) -> None:
    root = tmp_path.resolve() / "datos"
    db_path = tmp_path / "cache.db"
    async with CacheManager(db_path) as cache:
        await cache.save_entries([_status_entry(str(root / "x" / "a.pdf"), ConversionStatus.ERROR)])

    async with CacheManager(db_path, read_only=True) as cache:
        assert await cache.count_entries("x", relative_to=root, conversion_status=ConversionStatus.ERROR) == 1


def test_relative_path_sql_function_handles_both_separators() -> None:
    assert _py_relpath(r"C:\datos\x\a.pdf", r"C:\datos") == r"x\a.pdf"
    assert _py_relpath("/datos/x/a.pdf", "/datos") == "x/a.pdf"
    assert _py_relpath("/datos2/a.pdf", "/datos") is None  # mismo prefijo, otra carpeta
    assert _py_relpath("/a.pdf", "/") == "a.pdf"


@pytest.mark.asyncio
async def test_read_only_on_a_file_that_is_not_sqlite_raises_cache_error(tmp_path) -> None:
    db_path = tmp_path / "cache.db"
    db_path.write_bytes(b"esto no es una base de datos SQLite, solo texto" * 20)

    with pytest.raises(CacheError, match="No se pudo leer"):
        async with CacheManager(db_path, read_only=True):
            pass
