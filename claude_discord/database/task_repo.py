"""TaskRepository — CRUD for scheduled_tasks table.

Stores periodic Claude Code tasks registered via REST API or chat.
The scheduler Cog polls this table every 30 seconds and runs due tasks.
"""

from __future__ import annotations

import logging
import time

import aiosqlite

logger = logging.getLogger(__name__)

TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    prompt           TEXT    NOT NULL,
    interval_seconds INTEGER NOT NULL,
    channel_id       INTEGER NOT NULL,
    working_dir      TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    next_run_at      REAL    NOT NULL,
    last_run_at      REAL,
    created_at       REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_next_run
    ON scheduled_tasks(next_run_at, enabled);
"""


class TaskRepository:
    """Async CRUD for scheduled_tasks table."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        """Initialize the task schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(TASK_SCHEMA)
            await db.commit()
        logger.info("Task DB initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _db_execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a DML statement (for tests and internal use)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get(self, task_id: int) -> dict | None:
        """Return a single task by ID, or None if not found."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    async def get_all(self) -> list[dict]:
        """Return all tasks (enabled and disabled)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM scheduled_tasks ORDER BY created_at")
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            result.append(d)
        return result

    async def get_due(self, now: float | None = None) -> list[dict]:
        """Return enabled tasks whose next_run_at is in the past."""
        ts = now if now is not None else time.time()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM scheduled_tasks
                   WHERE enabled = 1 AND next_run_at <= ?
                   ORDER BY next_run_at""",
                (ts,),
            )
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        prompt: str,
        interval_seconds: int,
        channel_id: int,
        *,
        working_dir: str | None = None,
        run_immediately: bool = True,
    ) -> int:
        """Create a new scheduled task. Returns the created ID.

        Args:
            run_immediately: If True (default), set next_run_at = now so the
                task fires on the next master-loop tick. If False, delay by
                interval_seconds (useful for tasks that should wait one full
                cycle before the first run).
        """
        now = time.time()
        next_run = now if run_immediately else now + interval_seconds
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO scheduled_tasks
                   (name, prompt, interval_seconds, channel_id, working_dir,
                    enabled, next_run_at, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (name, prompt, interval_seconds, channel_id, working_dir, next_run, now),
            )
            await db.commit()
            row_id = cursor.lastrowid
        assert row_id is not None
        logger.info(
            "Scheduled task created: id=%d, name=%s, interval=%ds", row_id, name, interval_seconds
        )
        return row_id

    async def update_next_run(self, task_id: int, interval_seconds: int) -> None:
        """Advance next_run_at by interval_seconds and record last_run_at."""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE scheduled_tasks
                   SET next_run_at = ?, last_run_at = ?
                   WHERE id = ?""",
                (now + interval_seconds, now, task_id),
            )
            await db.commit()

    async def delete(self, task_id: int) -> bool:
        """Delete a task. Returns True if a row was deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def set_enabled(self, task_id: int, *, enabled: bool) -> bool:
        """Enable or disable a task. Returns True if updated."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE scheduled_tasks SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, task_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update(
        self,
        task_id: int,
        *,
        prompt: str | None = None,
        interval_seconds: int | None = None,
        working_dir: str | None = None,
    ) -> bool:
        """Partially update a task. Returns True if updated."""
        fields: list[str] = []
        values: list[object] = []
        if prompt is not None:
            fields.append("prompt = ?")
            values.append(prompt)
        if interval_seconds is not None:
            fields.append("interval_seconds = ?")
            values.append(interval_seconds)
        if working_dir is not None:
            fields.append("working_dir = ?")
            values.append(working_dir)
        if not fields:
            return False
        values.append(task_id)
        sql = f"UPDATE scheduled_tasks SET {', '.join(fields)} WHERE id = ?"  # noqa: S608
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(sql, tuple(values))
            await db.commit()
            return cursor.rowcount > 0
