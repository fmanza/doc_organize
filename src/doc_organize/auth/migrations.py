"""Schema migrations for AuthStore database.

This module provides a Protocol-based migration system that tracks schema
versions and applies migrations in order. Each migration is idempotent and
can be safely applied multiple times.

Pattern:
    1. Define schema version (see schema_version table)
    2. Implement migrations in order (Migration001, Migration002, ...)
    3. Add to MIGRATIONS list
    4. Each migration has up() and optional down() for rollback
"""

import sqlite3

from datetime import UTC, datetime
from typing import Any, Protocol

import aiosqlite


class SchemaMigration(Protocol):
    """Protocol for schema migrations.

    Each migration MUST be idempotent (safe to apply multiple times)
    and MUST handle both fresh installations and upgrades from previous versions.
    """

    version: int
    description: str

    async def up(self, conn: aiosqlite.Connection) -> None:
        """Apply migration (upgrade schema to this version)."""
        ...

    async def down(self, conn: aiosqlite.Connection) -> None:
        """Rollback migration (downgrade schema to previous version).

        Optional: not all migrations need down() implementation.
        """
        ...


class Migration001InitialSchema:
    """Initial schema: users, roles, sessions, projects tables."""

    version = 1
    description = "Initial schema with users, roles, sessions"

    async def up(self, conn: aiosqlite.Connection) -> None:
        """Create initial tables if they don't exist."""
        # Tables are created by _SCHEMA in auth_store.__init__()
        # This migration is a no-op for tracking purposes

    async def down(self, conn: aiosqlite.Connection) -> None:
        """Migration 001 has no rollback (base schema)."""
        raise NotImplementedError("Cannot rollback initial schema")


class Migration002AddUserColumns:
    """Add user columns: role_id, must_change_password, is_blocked, is_instance_admin."""

    version = 2
    description = "Add user management columns (role_id, must_change_password, is_blocked, is_instance_admin)"

    async def up(self, conn: aiosqlite.Connection) -> None:
        """Idempotently add missing columns to users table."""
        cursor = await conn.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cursor.fetchall()}

        # Add role_id column (foreign key to roles)
        if "role_id" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN role_id TEXT REFERENCES roles(id)")

        # Add must_change_password column
        if "must_change_password" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

        # Add is_blocked column
        if "is_blocked" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")

        # Add is_instance_admin column
        if "is_instance_admin" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN is_instance_admin INTEGER NOT NULL DEFAULT 0")

        await conn.commit()

    async def down(self, conn: aiosqlite.Connection) -> None:
        """Remove added columns (requires table recreation in SQLite)."""
        # SQLite doesn't support DROP COLUMN with constraints
        # Rollback would require table recreation (complex, rarely needed)
        raise NotImplementedError("Rollback of user column additions requires table recreation")


class Migration003RefactorRolesSchema:
    """Refactor roles schema: remove tenant_id (roles are now instance-wide)."""

    version = 3
    description = "Refactor roles: remove tenant_id, make names globally unique"

    async def up(self, conn: aiosqlite.Connection) -> None:
        """Recreate roles table without tenant_id column."""
        cursor = await conn.execute("PRAGMA table_info(roles)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "tenant_id" not in columns:
            return  # Already migrated or fresh installation

        # Fetch existing roles
        cursor = await conn.execute("SELECT id, tenant_id, name, is_admin, created_at FROM roles ORDER BY created_at")
        rows = await cursor.fetchall()

        # Dedup role names: if duplicate across tenants, append tenant_id
        final_names: dict[str, str] = {}
        seen_lower: set[str] = set()
        renamed_count = 0

        for role_id, tenant_id, name, _is_admin, _created_at in rows:
            candidate = name
            if candidate.lower() in seen_lower:
                candidate = f"{name} ({tenant_id})"
                suffix = 2
                while candidate.lower() in seen_lower:
                    candidate = f"{name} ({tenant_id}-{suffix})"
                    suffix += 1
                renamed_count += 1
            seen_lower.add(candidate.lower())
            final_names[role_id] = candidate

        # Recreate table without tenant_id
        await conn.execute("PRAGMA foreign_keys=OFF")
        try:
            await conn.execute(
                "CREATE TABLE roles_new ("
                "  id TEXT PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  is_admin INTEGER NOT NULL DEFAULT 0,"
                "  created_at TEXT NOT NULL,"
                "  UNIQUE(name COLLATE NOCASE)"
                ")"
            )

            # Copy rows with deduplicated names
            for role_id, _tenant_id, _name, is_admin, created_at in rows:
                await conn.execute(
                    "INSERT INTO roles_new (id, name, is_admin, created_at) VALUES (?, ?, ?, ?)",
                    (role_id, final_names[role_id], is_admin, created_at),
                )

            # Drop old table and rename new one
            await conn.execute("DROP TABLE roles")
            await conn.execute("ALTER TABLE roles_new RENAME TO roles")
            await conn.execute("DROP TABLE IF EXISTS role_scan_roots")
            await conn.commit()
        finally:
            await conn.execute("PRAGMA foreign_keys=ON")

        if renamed_count:
            logger_info = f"Migration 003: {renamed_count} role(s) renamed for global uniqueness"
            print(logger_info)  # In real code, use self.logger.warning()

    async def down(self, conn: aiosqlite.Connection) -> None:
        """Rollback requires restoring tenant_id column (complex, rarely needed)."""
        raise NotImplementedError("Rollback of roles refactor requires data restoration")


class Migration004BackfillRoles:
    """Backfill missing roles for users without role_id."""

    version = 4
    description = "Backfill missing roles and instance_admin flags"

    async def up(self, conn: aiosqlite.Connection) -> None:
        """Assign admin role to users without role_id."""
        # Get or create admin role
        cursor = await conn.execute("SELECT id FROM roles WHERE is_admin = 1 ORDER BY created_at LIMIT 1")
        row = await cursor.fetchone()
        admin_role_id = row[0] if row else None

        if not admin_role_id:
            # Create admin role if it doesn't exist
            import uuid

            admin_role_id = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO roles (id, name, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (admin_role_id, "admin", 1, datetime.now(UTC).isoformat()),
            )
            await conn.commit()

        # Backfill users without role_id with admin role
        cursor = await conn.execute("SELECT COUNT(*) FROM users WHERE role_id IS NULL")
        count_row = await cursor.fetchone()
        if count_row and count_row[0] > 0:
            await conn.execute(
                "UPDATE users SET role_id = ? WHERE role_id IS NULL",
                (admin_role_id,),
            )
            await conn.commit()

    async def down(self, conn: aiosqlite.Connection) -> None:
        """Rollback by clearing role_id for migrated users."""
        await conn.execute("UPDATE users SET role_id = NULL")
        await conn.commit()


class Migration005BackfillInstanceAdmins:
    """Backfill instance_admin flags for users."""

    version = 5
    description = "Backfill instance_admin flags from legacy data"

    async def up(self, conn: aiosqlite.Connection) -> None:
        """Promote to is_instance_admin=True for admins of DEFAULT_TENANT_ID or oldest user.

        This implements the old _backfill_instance_admins() logic:
        1. If any user already has is_instance_admin=True, skip (already migrated)
        2. If DEFAULT_TENANT_ID has admins with is_admin=True, promote them
        3. Otherwise, promote the oldest user in the entire installation
        """
        from doc_organize.core.constants import DEFAULT_TENANT_ID

        # Check if any user already has is_instance_admin=True
        cursor = await conn.execute("SELECT COUNT(*) FROM users WHERE is_instance_admin = 1")
        count_row = await cursor.fetchone()
        if count_row and count_row[0] > 0:
            return  # Already migrated

        # Find admin users from DEFAULT_TENANT_ID
        cursor = await conn.execute(
            "SELECT u.id FROM users u JOIN roles r ON u.role_id = r.id WHERE u.tenant_id = ? AND r.is_admin = 1 ORDER BY u.created_at",
            (DEFAULT_TENANT_ID,),
        )
        promoted_ids = [row[0] for row in await cursor.fetchall()]

        # If no admins in DEFAULT_TENANT_ID, promote oldest user
        if not promoted_ids:
            cursor = await conn.execute("SELECT id FROM users ORDER BY created_at LIMIT 1")
            row = await cursor.fetchone()
            if row is None:
                return  # No users at all
            promoted_ids = [row[0]]

        # Promote selected users
        if promoted_ids:
            await conn.executemany(
                "UPDATE users SET is_instance_admin = 1 WHERE id = ?",
                [(user_id,) for user_id in promoted_ids],
            )
            await conn.commit()

    async def down(self, conn: aiosqlite.Connection) -> None:
        """Clear backfilled instance_admin flags."""
        await conn.execute("UPDATE users SET is_instance_admin = 0")


# Ordered list of migrations
MIGRATIONS: list[Any] = [
    Migration001InitialSchema(),
    Migration002AddUserColumns(),
    Migration003RefactorRolesSchema(),
    Migration004BackfillRoles(),
    Migration005BackfillInstanceAdmins(),
]


async def get_schema_version(conn: aiosqlite.Connection) -> int:
    """Get current schema version from database.

    Returns:
        Current version (0 if schema_version table doesn't exist)
    """
    try:
        cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return 0


async def apply_pending_migrations(conn: aiosqlite.Connection, logger: Any = None) -> int:
    """Apply all pending migrations.

    Args:
        conn: aiosqlite connection
        logger: Optional logger for warnings/info

    Returns:
        Final schema version after migrations
    """
    # Ensure schema_version table exists
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY,
            version INTEGER UNIQUE NOT NULL,
            applied_at TEXT NOT NULL,
            description TEXT
        )"""
    )
    await conn.commit()

    current_version = await get_schema_version(conn)

    # Apply pending migrations
    for migration in MIGRATIONS:
        if migration.version > current_version:
            try:
                await migration.up(conn)
                await conn.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (migration.version, datetime.now(UTC).isoformat(), migration.description),
                )
                await conn.commit()
                if logger:
                    logger.info(f"Applied migration {migration.version}: {migration.description}")
            except Exception as e:
                await conn.rollback()
                if logger:
                    logger.error(f"Failed to apply migration {migration.version}: {e}")
                raise

    return await get_schema_version(conn)
