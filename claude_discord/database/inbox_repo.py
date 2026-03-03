"""Thread inbox repository — persistent tracking of threads awaiting user reply."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import aiosqlite

logger = logging.getLogger(__name__)

InboxStatus = Literal["waiting", "ambiguous"]
InboxConfidence = Literal["high", "low"]


@dataclass(frozen=True)
class InboxEntry:
    thread_id: int
    status: InboxStatus
    confidence: InboxConfidence
    last_message_url: str | None
    updated_at: str


class ThreadInboxRepository:
    """CRUD for the thread_inbox table.

    All methods open a short-lived connection; this matches the pattern
    used by the other repositories in this package.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def upsert(
        self,
        thread_id: int,
        status: InboxStatus,
        confidence: InboxConfidence = "high",
        last_message_url: str | None = None,
    ) -> None:
        """Insert or replace an inbox entry."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO thread_inbox (thread_id, status, confidence, last_message_url,
                                          updated_at)
                VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(thread_id) DO UPDATE SET
                    status = excluded.status,
                    confidence = excluded.confidence,
                    last_message_url = excluded.last_message_url,
                    updated_at = excluded.updated_at
                """,
                (thread_id, status, confidence, last_message_url),
            )
            await db.commit()
        logger.debug("inbox upsert thread_id=%d status=%s", thread_id, status)

    async def remove(self, thread_id: int) -> bool:
        """Delete an inbox entry. Returns True if a row was deleted."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM thread_inbox WHERE thread_id = ?", (thread_id,))
            await db.commit()
            deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("inbox remove thread_id=%d", thread_id)
        return deleted

    async def list_all(self) -> list[InboxEntry]:
        """Return all inbox entries ordered by most-recently updated."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT thread_id, status, confidence, last_message_url, updated_at"
                " FROM thread_inbox ORDER BY updated_at DESC"
            )
            rows = await cursor.fetchall()
        return [
            InboxEntry(
                thread_id=row["thread_id"],
                status=row["status"],
                confidence=row["confidence"],
                last_message_url=row["last_message_url"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
