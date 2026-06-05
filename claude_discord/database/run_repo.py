"""RunRepository — storage for async one-shot AI run jobs (/api/run).

A "run" is a single, non-interactive AI invocation: a prompt is dispatched
to an engine (claude/codex/…), executed in the background, and its final
text is stored here for later retrieval by ``run_id``.

Frontend- and engine-agnostic: this table knows nothing about Discord,
customers, or which backend produced the text. The prompt itself is NOT
persisted — only the engine selection, status, and final output — so that
sensitive request bodies never linger in the database.
"""

from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)

RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'running',
    backend    TEXT NOT NULL,
    model      TEXT NOT NULL,
    result     TEXT,
    error      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
"""


class RunRepository:
    """Async CRUD for the runs table."""

    # Keep at most this many recent runs to prevent unbounded growth.
    MAX_STORED_RUNS = 200

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        """Create the runs schema if it does not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(RUN_SCHEMA)
            await db.commit()
        logger.info("Run DB initialized at %s", self.db_path)

    async def create(self, *, run_id: str, backend: str, model: str) -> dict:
        """Insert a new run in the 'running' state and return it."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO runs (run_id, status, backend, model) VALUES (?, 'running', ?, ?)",
                (run_id, backend, model),
            )
            # Prune old rows, keeping only the most recent MAX_STORED_RUNS.
            await db.execute(
                "DELETE FROM runs WHERE run_id NOT IN "
                "(SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                (self.MAX_STORED_RUNS,),
            )
            await db.commit()
        logger.info("Run created: run_id=%s backend=%s model=%s", run_id, backend, model)
        rec = await self.get(run_id)
        if rec is None:
            raise RuntimeError(f"Failed to retrieve run {run_id} after insert")
        return rec

    async def get(self, run_id: str) -> dict | None:
        """Return a single run by id, or None if not found."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def set_result(self, run_id: str, result: str) -> None:
        """Mark a run done and store its final text."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE runs SET status = 'done', result = ?, "
                "updated_at = datetime('now', 'localtime') WHERE run_id = ?",
                (result, run_id),
            )
            await db.commit()
        logger.info("Run done: run_id=%s (%d chars)", run_id, len(result))

    async def set_error(self, run_id: str, error: str) -> None:
        """Mark a run failed and store the error message."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE runs SET status = 'error', error = ?, "
                "updated_at = datetime('now', 'localtime') WHERE run_id = ?",
                (error, run_id),
            )
            await db.commit()
        logger.warning("Run error: run_id=%s", run_id)

    async def count(self) -> int:
        """Return the number of stored runs."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM runs")
            row = await cursor.fetchone()
        return int(row[0]) if row else 0
