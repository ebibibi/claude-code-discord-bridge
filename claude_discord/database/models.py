"""SQLite database schema and initialization."""

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
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_last_used ON sessions(last_used_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_asks (
    thread_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    question_idx INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS lounge_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL DEFAULT 'AI',
    message TEXT NOT NULL,
    posted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_lounge_posted_at ON lounge_messages(posted_at);

-- Sessions that should be resumed after a bot restart.
-- Rows expire automatically via TTL checks in PendingResumeRepository.
-- A Claude session that is about to restart the bot writes a row here first;
-- on_ready reads and deletes it to resume the session.
CREATE TABLE IF NOT EXISTS pending_resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL UNIQUE,
    session_id TEXT,           -- optional: used for "claude --resume" continuity
    reason TEXT NOT NULL DEFAULT 'self_restart',
    resume_prompt TEXT,        -- message to post + send to Claude on resume
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Project Board: persistent structured tracking of all projects/tasks.
-- Unlike lounge (ephemeral chat), board items have status, category, blocker.
CREATE TABLE IF NOT EXISTS board_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'not_started',
    blocker TEXT,
    next_action TEXT,
    priority INTEGER NOT NULL DEFAULT 3,
    wf_id TEXT,
    owner TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_board_status ON board_items(status);
CREATE INDEX IF NOT EXISTS idx_board_category ON board_items(category);
CREATE INDEX IF NOT EXISTS idx_board_priority ON board_items(priority);

-- Usage tracking: per-session cost/token/duration records for billing visibility.
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    session_id TEXT,
    discord_user_id TEXT,
    discord_username TEXT,
    bot_name TEXT,
    model TEXT,
    cost_usd REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    duration_ms INTEGER,
    prompt_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(discord_user_id);
CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_records(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_bot ON usage_records(bot_name);
"""

# Migrations for existing databases that lack new columns.
_MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN origin TEXT NOT NULL DEFAULT 'discord'",
    "ALTER TABLE sessions ADD COLUMN summary TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)",
    # Lounge table added in v1.x — safe to run on existing DBs
    (
        "CREATE TABLE IF NOT EXISTS lounge_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "label TEXT NOT NULL DEFAULT 'AI', "
        "message TEXT NOT NULL, "
        "posted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
    ),
    "CREATE INDEX IF NOT EXISTS idx_lounge_posted_at ON lounge_messages(posted_at)",
    # pending_resumes added in v1.3 — safe to run on existing DBs
    (
        "CREATE TABLE IF NOT EXISTS pending_resumes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "thread_id INTEGER NOT NULL UNIQUE, "
        "session_id TEXT, "
        "reason TEXT NOT NULL DEFAULT 'self_restart', "
        "resume_prompt TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
    ),
    # board_items added for Project Board feature
    (
        "CREATE TABLE IF NOT EXISTS board_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT NOT NULL, "
        "category TEXT NOT NULL DEFAULT 'other', "
        "status TEXT NOT NULL DEFAULT 'not_started', "
        "blocker TEXT, "
        "next_action TEXT, "
        "priority INTEGER NOT NULL DEFAULT 3, "
        "wf_id TEXT, "
        "owner TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
    ),
    "CREATE INDEX IF NOT EXISTS idx_board_status ON board_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_board_category ON board_items(category)",
    "CREATE INDEX IF NOT EXISTS idx_board_priority ON board_items(priority)",
    # channel_id for cross-thread context — added in v1.5
    "ALTER TABLE sessions ADD COLUMN channel_id INTEGER",
    "CREATE INDEX IF NOT EXISTS idx_sessions_channel ON sessions(channel_id)",
    # usage_records for cost/token tracking — added for billing visibility
    (
        "CREATE TABLE IF NOT EXISTS usage_records ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "thread_id INTEGER NOT NULL, "
        "session_id TEXT, "
        "discord_user_id TEXT, "
        "discord_username TEXT, "
        "bot_name TEXT, "
        "model TEXT, "
        "cost_usd REAL, "
        "input_tokens INTEGER, "
        "output_tokens INTEGER, "
        "cache_read_tokens INTEGER, "
        "cache_creation_tokens INTEGER, "
        "duration_ms INTEGER, "
        "prompt_summary TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
    ),
    "CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(discord_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_records(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_bot ON usage_records(bot_name)",
]


async def init_db(db_path: str) -> None:
    """Initialize the database with the schema.

    For fresh databases the full SCHEMA is applied. For existing databases
    the migration statements add any missing columns idempotently.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        for stmt in _MIGRATIONS:
            with contextlib.suppress(Exception):
                await db.execute(stmt)
        await db.commit()
    logger.info("Database initialized at %s", db_path)
