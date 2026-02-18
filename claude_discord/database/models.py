"""SQLite database schema and initialization."""

from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    thread_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    working_dir TEXT,
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_last_used ON sessions(last_used_at);
"""


async def init_db(db_path: str) -> None:
    """Initialize the database with the schema."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    logger.info("Database initialized at %s", db_path)
