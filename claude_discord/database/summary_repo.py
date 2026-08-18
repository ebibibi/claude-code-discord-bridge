"""ThreadSummaryRepository — running summaries for long external threads.

Some ingest clients (notably the Teams browser extension) keep talking in a
single upstream thread for months, accumulating hundreds of messages. Re-sending
the whole history to every ingest run is wasteful. Instead the client sends only
the *new* messages (a diff) and ccdb keeps a compact running summary of the
thread, keyed by a stable client-provided ``summary_key`` (e.g. the Teams thread
root message id).

The flow:

1. Before exporting, the client calls ``GET /api/ingest/summary?key=...`` to read
   the stored summary and ``marker`` (the newest upstream message already folded
   into the summary). It exports only messages newer than ``marker``.
2. On ingest, ccdb injects the stored summary into the prompt so the Claude
   session has full historical context even though the attachment is just the
   diff.
3. When the session finishes, Claude POSTs an updated summary back
   (``POST /api/ingest/summary``); ccdb advances ``marker`` to the newest message
   from that ingest, atomically with the new summary text.

Only the distilled summary + marker are stored here — never the raw messages.
The Discord thread remains the source of truth for any single interaction.
"""

from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)

THREAD_SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS thread_summaries (
    summary_key TEXT PRIMARY KEY,
    summary     TEXT NOT NULL DEFAULT '',
    marker      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_thread_summaries_updated ON thread_summaries(updated_at);
"""


class ThreadSummaryRepository:
    """Async CRUD for the thread_summaries table."""

    # Keep at most this many recent summaries to prevent unbounded growth.
    MAX_STORED_SUMMARIES = 1000

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        """Create the thread_summaries schema if it does not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(THREAD_SUMMARY_SCHEMA)
            await db.commit()
        logger.info("Thread summary DB initialized at %s", self.db_path)

    async def get(self, summary_key: str) -> dict | None:
        """Return the stored summary for a key, or None if unknown."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM thread_summaries WHERE summary_key = ?", (summary_key,)
            )
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def upsert(self, summary_key: str, *, summary: str, marker: str | None = None) -> dict:
        """Insert or update a summary.

        When ``marker`` is ``None`` on an update, the previously stored marker is
        preserved (a summary refresh that does not advance the read position must
        not blank out a known marker). On first insert a ``None`` marker is stored
        as ``NULL``.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # COALESCE(excluded.marker, thread_summaries.marker): only advance the
            # marker when the caller supplies one; otherwise keep the old value.
            await db.execute(
                """
                INSERT INTO thread_summaries (summary_key, summary, marker)
                VALUES (?, ?, ?)
                ON CONFLICT(summary_key) DO UPDATE SET
                    summary = excluded.summary,
                    marker = COALESCE(excluded.marker, thread_summaries.marker),
                    updated_at = datetime('now', 'localtime')
                """,
                (summary_key, summary, marker),
            )
            # Prune old rows, keeping only the most recent MAX_STORED_SUMMARIES.
            await db.execute(
                "DELETE FROM thread_summaries WHERE summary_key NOT IN "
                "(SELECT summary_key FROM thread_summaries "
                "ORDER BY updated_at DESC, rowid DESC LIMIT ?)",
                (self.MAX_STORED_SUMMARIES,),
            )
            await db.commit()
        rec = await self.get(summary_key)
        if rec is None:
            raise RuntimeError(f"Failed to retrieve thread summary {summary_key} after upsert")
        logger.info(
            "Thread summary saved: key=%s (%d chars) marker=%s",
            summary_key,
            len(summary),
            rec["marker"],
        )
        return rec

    async def delete(self, summary_key: str) -> bool:
        """Delete a summary. Returns True if a row was removed."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM thread_summaries WHERE summary_key = ?", (summary_key,)
            )
            await db.commit()
            removed = cursor.rowcount > 0
        if removed:
            logger.info("Thread summary deleted: key=%s", summary_key)
        return removed

    async def count(self) -> int:
        """Return the number of stored summaries."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM thread_summaries")
            row = await cursor.fetchone()
        return int(row[0]) if row else 0
