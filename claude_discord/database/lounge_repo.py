"""Repository for AI Lounge messages.

The AI Lounge is a shared space where concurrent Claude Code sessions leave
short, human-readable notes for each other.  Unlike the dry concurrency
registry (which tracks technical state), lounge messages are written in the
AI's own words — casual updates, reactions to their tasks, coordination
requests — and are routed to a Discord channel so humans can observe the
conversation.

Messages are stored in the shared SQLite sessions DB to avoid an additional
file dependency.  Old messages are pruned automatically to keep the table small.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

logger = logging.getLogger(__name__)

# Keep at most this many recent messages to prevent unbounded growth.
_MAX_STORED_MESSAGES = 200


@dataclass
class LoungeMessage:
    """A single AI Lounge message."""

    id: int
    label: str
    message: str
    posted_at: str  # ISO datetime string (localtime)


class LoungeRepository:
    """Read/write AI Lounge messages from SQLite.

    All operations use the shared sessions DB so no extra file is needed.
    The table is created by models.init_db() via the migrations list.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def post(self, message: str, label: str = "AI") -> LoungeMessage:
        """Insert a new lounge message and return it.

        Prunes messages exceeding _MAX_STORED_MESSAGES after insert.
        """
        label = (label or "AI")[:50]  # safety cap
        message = (message or "")[:1000]  # safety cap

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "INSERT INTO lounge_messages (label, message) VALUES (?, ?)",
                (label, message),
            )
            row_id = cursor.lastrowid
            await db.commit()

            # Fetch the inserted row (to get server-generated posted_at)
            cur = await db.execute(
                "SELECT id, label, message, posted_at FROM lounge_messages WHERE id = ?",
                (row_id,),
            )
            row = await cur.fetchone()

            # Prune old messages — keep only the most recent _MAX_STORED_MESSAGES
            await db.execute(
                "DELETE FROM lounge_messages WHERE id NOT IN "
                "(SELECT id FROM lounge_messages ORDER BY id DESC LIMIT ?)",
                (_MAX_STORED_MESSAGES,),
            )
            await db.commit()

        if row is None:
            raise RuntimeError(f"Failed to retrieve lounge message id={row_id}")

        result = LoungeMessage(
            id=row["id"],
            label=row["label"],
            message=row["message"],
            posted_at=row["posted_at"],
        )
        logger.info("Lounge message posted by %r (id=%d)", label, result.id)
        return result

    async def get_recent(self, limit: int = 10) -> list[LoungeMessage]:
        """Return the most recent lounge messages, oldest first.

        Args:
            limit: Maximum number of messages to return (default 10).
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Pick the N newest via subquery, then sort ascending for display
            rows = await db.execute_fetchall(
                "SELECT id, label, message, posted_at FROM ("
                "  SELECT id, label, message, posted_at FROM lounge_messages"
                "  ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC",
                (limit,),
            )

        return [
            LoungeMessage(
                id=row["id"],
                label=row["label"],
                message=row["message"],
                posted_at=row["posted_at"],
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return the total number of stored lounge messages."""
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM lounge_messages")
            row = await cur.fetchone()
        return row[0] if row else 0
