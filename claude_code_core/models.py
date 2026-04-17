"""Minimal SQLite database schema for Claude Code core.

Contains only the tables needed by any Claude Code integration:
- sessions: thread/channel-to-session mapping
- usage_stats: rate limit tracking

Frontend-specific tables (pending_asks, lounge_messages, pending_resumes,
thread_inbox, settings) remain in the frontend package (e.g. ccdb).
"""

from __future__ import annotations

import contextlib
import logging

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    thread_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    working_dir TEXT,
    model TEXT,
    origin TEXT NOT NULL DEFAULT 'discord',
    summary TEXT,
    context_window INTEGER,
    context_used INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_last_used ON sessions(last_used_at);
CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);

CREATE TABLE IF NOT EXISTS usage_stats (
    rate_limit_type TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    utilization REAL NOT NULL,
    resets_at INTEGER NOT NULL,
    is_using_overage INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# Migrations for existing databases that lack new columns.
_MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN origin TEXT NOT NULL DEFAULT 'discord'",
    "ALTER TABLE sessions ADD COLUMN summary TEXT",
    "ALTER TABLE sessions ADD COLUMN context_window INTEGER",
    "ALTER TABLE sessions ADD COLUMN context_used INTEGER",
    # Drop UNIQUE constraint on session_id to allow fork (multiple threads, same source session)
    "DROP INDEX IF EXISTS idx_sessions_session_id",
    "CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)",
    (
        "CREATE TABLE IF NOT EXISTS usage_stats ("
        "rate_limit_type TEXT PRIMARY KEY, "
        "status TEXT NOT NULL, "
        "utilization REAL NOT NULL, "
        "resets_at INTEGER NOT NULL, "
        "is_using_overage INTEGER NOT NULL DEFAULT 0, "
        "recorded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
    ),
]


async def init_db(db_path: str) -> None:
    """Initialize the database with the core schema.

    For fresh databases the full SCHEMA is applied. For existing databases
    the migration statements add any missing columns idempotently.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        for stmt in _MIGRATIONS:
            with contextlib.suppress(Exception):
                await db.execute(stmt)
        await db.commit()
    logger.info("Core database initialized at %s", db_path)
