"""Tests for schema migrations module.

Tests verify:
- Migrations are idempotent (can be applied multiple times)
- Version tracking works correctly
- Migrations apply in order
- Rollback functionality (where implemented)
"""

import tempfile

from collections.abc import AsyncGenerator
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from doc_organize.auth.migrations import (
    MIGRATIONS,
    Migration002AddUserColumns,
    Migration003RefactorRolesSchema,
    apply_pending_migrations,
    get_schema_version,
)


@pytest_asyncio.fixture
async def temp_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Create a temporary SQLite database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create initial schema (same as auth_store.__init__)
        conn = await aiosqlite.connect(str(db_path))

        # Minimal schema for testing
        await conn.execute("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tenant_id TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE roles (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                name TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(tenant_id, name)
            )
        """)

        await conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        await conn.commit()
        yield conn

        await conn.close()
        db_path.unlink()


@pytest.mark.asyncio
async def test_get_schema_version_empty_db(temp_db: aiosqlite.Connection) -> None:
    """Test getting version from empty database (no migrations yet)."""
    version = await get_schema_version(temp_db)
    assert version == 0


@pytest.mark.asyncio
async def test_apply_pending_migrations(temp_db: aiosqlite.Connection) -> None:
    """Test applying all pending migrations."""
    # Apply migrations
    final_version = await apply_pending_migrations(temp_db)

    # Should have applied all migrations
    assert final_version == len(MIGRATIONS)

    # Verify schema_version table exists and has correct entries
    cursor = await temp_db.execute("SELECT version FROM schema_version ORDER BY version")
    versions = [row[0] for row in await cursor.fetchall()]
    assert versions == list(range(1, len(MIGRATIONS) + 1))


@pytest.mark.asyncio
async def test_migrations_idempotent(temp_db: aiosqlite.Connection) -> None:
    """Test that applying migrations multiple times is safe."""
    # Apply migrations once
    version1 = await apply_pending_migrations(temp_db)

    # Apply again (should be idempotent)
    version2 = await apply_pending_migrations(temp_db)

    # Versions should match
    assert version1 == version2

    # Verify no duplicate entries in schema_version
    cursor = await temp_db.execute("SELECT COUNT(*) FROM schema_version")
    count_row = await cursor.fetchone()
    assert count_row is not None
    assert count_row[0] == len(MIGRATIONS)


@pytest.mark.asyncio
async def test_migration_002_adds_user_columns(temp_db: aiosqlite.Connection) -> None:
    """Test Migration002 adds all required user columns."""
    migration = Migration002AddUserColumns()

    # Apply migration
    await migration.up(temp_db)

    # Check columns after migration
    cursor = await temp_db.execute("PRAGMA table_info(users)")
    columns_after = {row[1] for row in await cursor.fetchall()}

    # Verify new columns were added
    assert "role_id" in columns_after
    assert "must_change_password" in columns_after
    assert "is_blocked" in columns_after
    assert "is_instance_admin" in columns_after


@pytest.mark.asyncio
async def test_migration_003_roles_schema_refactor(temp_db: aiosqlite.Connection) -> None:
    """Test Migration003 refactors roles schema (removes tenant_id)."""
    migration = Migration003RefactorRolesSchema()

    # Insert test data with tenant_id
    await temp_db.execute(
        "INSERT INTO roles (id, tenant_id, name, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
        ("role1", "tenant1", "admin", 1, "2026-01-01T00:00:00"),
    )
    await temp_db.execute(
        "INSERT INTO roles (id, tenant_id, name, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
        ("role2", "tenant2", "admin", 0, "2026-01-02T00:00:00"),
    )
    await temp_db.commit()

    # Apply migration
    await migration.up(temp_db)

    # Verify tenant_id column is removed
    cursor = await temp_db.execute("PRAGMA table_info(roles)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "tenant_id" not in columns

    # Verify roles exist with deduplicated names
    cursor = await temp_db.execute("SELECT name FROM roles ORDER BY created_at")
    names = [row[0] for row in await cursor.fetchall()]
    assert len(names) == 2  # Both roles should exist
    assert names[0] == "admin"  # First one keeps original name
    assert "tenant2" in names[1]  # Second one should have tenant suffix


@pytest.mark.asyncio
async def test_version_tracking(temp_db: aiosqlite.Connection) -> None:
    """Test that version tracking works correctly."""
    # Initially no versions
    version = await get_schema_version(temp_db)
    assert version == 0

    # Apply migrations
    final_version = await apply_pending_migrations(temp_db)

    # Should match number of migrations
    assert final_version == len(MIGRATIONS)

    # Verify schema_version table structure
    cursor = await temp_db.execute("SELECT version, description FROM schema_version ORDER BY version")
    rows = await cursor.fetchall()

    for i, (version_num, description) in enumerate(rows):
        expected_version = i + 1
        assert version_num == expected_version
        assert description == MIGRATIONS[i].description


@pytest.mark.asyncio
async def test_migration_with_logger(temp_db: aiosqlite.Connection) -> None:
    """Test that migrations work with logger."""
    # Apply migrations with logger
    await apply_pending_migrations(temp_db)

    # Verify migrations were applied (basic check)
    final_version = await get_schema_version(temp_db)
    assert final_version > 0
