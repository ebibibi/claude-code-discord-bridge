"""Session repository for thread-to-session mapping."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    """A stored session mapping."""

    thread_id: int
    session_id: str
    working_dir: str | None
    model: str | None
    origin: str
    summary: str | None
    created_at: str
    last_used_at: str
    channel_id: int | None = None


class SessionRepository:
    """CRUD operations for session records."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def get(self, thread_id: int) -> SessionRecord | None:
        """Get session by Discord thread ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE thread_id = ?",
                (thread_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return SessionRecord(**dict(row))

    async def save(
        self,
        thread_id: int,
        session_id: str,
        working_dir: str | None = None,
        model: str | None = None,
        origin: str = "discord",
        summary: str | None = None,
        channel_id: int | None = None,
    ) -> SessionRecord:
        """Create or update a session mapping."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO sessions
                     (thread_id, session_id, working_dir, model, origin, summary, channel_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(thread_id) DO UPDATE SET
                     session_id = excluded.session_id,
                     working_dir = COALESCE(excluded.working_dir, sessions.working_dir),
                     model = COALESCE(excluded.model, sessions.model),
                     origin = COALESCE(excluded.origin, sessions.origin),
                     summary = COALESCE(excluded.summary, sessions.summary),
                     channel_id = COALESCE(excluded.channel_id, sessions.channel_id),
                     last_used_at = datetime('now', 'localtime')""",
                (thread_id, session_id, working_dir, model, origin, summary, channel_id),
            )
            await db.commit()

        record = await self.get(thread_id)
        if record is None:
            raise RuntimeError(f"Failed to retrieve session after save for thread {thread_id}")
        return record

    async def get_by_session_id(self, session_id: str) -> SessionRecord | None:
        """Reverse lookup: get session by Claude Code session ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return SessionRecord(**dict(row))

    async def list_all(self, limit: int = 50, origin: str | None = None) -> list[SessionRecord]:
        """List all sessions ordered by most recently used.

        Args:
            limit: Maximum number of records to return.
            origin: Optional filter by origin ('discord', 'cli'). None returns all.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if origin:
                cursor = await db.execute(
                    "SELECT * FROM sessions WHERE origin = ? ORDER BY last_used_at DESC LIMIT ?",
                    (origin, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM sessions ORDER BY last_used_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [SessionRecord(**dict(row)) for row in rows]

    async def delete(self, thread_id: int) -> bool:
        """Delete a session mapping. Returns True if a row was deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE thread_id = ?",
                (thread_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_recent_summaries(
        self,
        channel_id: int,
        limit: int = 10,
        exclude_thread: int | None = None,
    ) -> list[SessionRecord]:
        """Get recent sessions with summaries from the same channel.

        Used for cross-thread context injection — lets new sessions know
        what was discussed in recent threads of the same channel.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if exclude_thread is not None:
                cursor = await db.execute(
                    """SELECT * FROM sessions
                       WHERE channel_id = ? AND thread_id != ? AND summary IS NOT NULL
                       ORDER BY last_used_at DESC LIMIT ?""",
                    (channel_id, exclude_thread, limit),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM sessions
                       WHERE channel_id = ? AND summary IS NOT NULL
                       ORDER BY last_used_at DESC LIMIT ?""",
                    (channel_id, limit),
                )
            rows = await cursor.fetchall()
            return [SessionRecord(**dict(row)) for row in rows]

    async def cleanup_old(self, days: int = 30) -> int:
        """Delete sessions older than N days. Returns count deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            query = (
                "DELETE FROM sessions"
                " WHERE julianday('now', 'localtime') - julianday(last_used_at) >= ?"
            )
            cursor = await db.execute(query, (days,))
            await db.commit()
            return cursor.rowcount
