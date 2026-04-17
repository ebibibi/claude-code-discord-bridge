"""Session repository for thread/channel-to-session mapping.

Frontend-agnostic: works with any integer key (Discord thread ID,
Teams conversation ID, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from .types import RateLimitInfo

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
    context_window: int | None = None
    context_used: int | None = None


class SessionRepository:
    """CRUD operations for session records."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def get(self, thread_id: int) -> SessionRecord | None:
        """Get session by thread/channel ID."""
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
    ) -> SessionRecord:
        """Create or update a session mapping."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO sessions
                     (thread_id, session_id, working_dir, model, origin, summary)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(thread_id) DO UPDATE SET
                     session_id = excluded.session_id,
                     working_dir = COALESCE(excluded.working_dir, sessions.working_dir),
                     model = COALESCE(excluded.model, sessions.model),
                     origin = COALESCE(excluded.origin, sessions.origin),
                     summary = COALESCE(excluded.summary, sessions.summary),
                     last_used_at = datetime('now', 'localtime')""",
                (thread_id, session_id, working_dir, model, origin, summary),
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

    async def update_context_stats(
        self,
        thread_id: int,
        context_window: int,
        context_used: int,
    ) -> None:
        """Persist context window stats for a session."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sessions SET context_window = ?, context_used = ? WHERE thread_id = ?",
                (context_window, context_used, thread_id),
            )
            await db.commit()


class UsageStatsRepository:
    """CRUD for rate limit usage stats (one row per rate_limit_type, upserted)."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def upsert(self, info: RateLimitInfo) -> None:
        """Insert or replace the latest rate limit info for the given type."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO usage_stats
                     (rate_limit_type, status, utilization, resets_at, is_using_overage)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(rate_limit_type) DO UPDATE SET
                     status = excluded.status,
                     utilization = excluded.utilization,
                     resets_at = excluded.resets_at,
                     is_using_overage = excluded.is_using_overage,
                     recorded_at = datetime('now', 'localtime')""",
                (
                    info.rate_limit_type,
                    info.status,
                    info.utilization,
                    info.resets_at,
                    int(info.is_using_overage),
                ),
            )
            await db.commit()

    async def get_latest(self) -> list[RateLimitInfo]:
        """Return all stored rate limit entries (one per type)."""
        from .types import RateLimitInfo as _RateLimitInfo

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM usage_stats ORDER BY rate_limit_type")
            rows = await cursor.fetchall()
            return [
                _RateLimitInfo(
                    rate_limit_type=row["rate_limit_type"],
                    status=row["status"],
                    utilization=row["utilization"],
                    resets_at=row["resets_at"],
                    is_using_overage=bool(row["is_using_overage"]),
                )
                for row in rows
            ]
