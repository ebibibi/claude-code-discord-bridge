"""Repository for pending AskUserQuestion state.

When Claude calls AskUserQuestion, we store the question data here before
showing Discord buttons.  If the bot is restarted before the user answers,
on_ready queries this table and re-registers persistent AskViews so old
buttons still work (showing a graceful "session ended" message rather than
the generic Discord "Interaction Failed").
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class PendingAskRecord:
    thread_id: int
    session_id: str
    questions_json: str  # JSON-serialised list[dict]
    question_idx: int
    created_at: str

    def questions(self) -> list[dict[str, Any]]:
        return json.loads(self.questions_json)  # type: ignore[no-any-return]


class PendingAskRepository:
    """Async SQLite repository for pending_asks rows."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def save(
        self,
        thread_id: int,
        session_id: str,
        questions: list[dict[str, Any]],
        question_idx: int = 0,
    ) -> None:
        """Insert or replace the pending ask for *thread_id*."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO pending_asks
                    (thread_id, session_id, questions_json, question_idx)
                VALUES (?, ?, ?, ?)
                """,
                (thread_id, session_id, json.dumps(questions), question_idx),
            )
            await db.commit()
        logger.debug(
            "PendingAskRepository: saved pending ask for thread %d (q_idx=%d)",
            thread_id,
            question_idx,
        )

    async def get(self, thread_id: int) -> PendingAskRecord | None:
        """Return the pending ask for *thread_id*, or None."""
        async with (
            aiosqlite.connect(self._db_path) as db,
            db.execute(
                "SELECT thread_id, session_id, questions_json, question_idx, created_at "
                "FROM pending_asks WHERE thread_id = ?",
                (thread_id,),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        if row is None:
            return None
        return PendingAskRecord(
            thread_id=row[0],
            session_id=row[1],
            questions_json=row[2],
            question_idx=row[3],
            created_at=row[4],
        )

    async def delete(self, thread_id: int) -> None:
        """Remove the pending ask for *thread_id* (called after answer received)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM pending_asks WHERE thread_id = ?", (thread_id,))
            await db.commit()
        logger.debug("PendingAskRepository: deleted pending ask for thread %d", thread_id)

    async def list_all(self) -> list[PendingAskRecord]:
        """Return all pending asks (used on bot startup for view recovery)."""
        async with (
            aiosqlite.connect(self._db_path) as db,
            db.execute(
                "SELECT thread_id, session_id, questions_json, question_idx, created_at "
                "FROM pending_asks ORDER BY created_at"
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        return [
            PendingAskRecord(
                thread_id=row[0],
                session_id=row[1],
                questions_json=row[2],
                question_idx=row[3],
                created_at=row[4],
            )
            for row in rows
        ]

    async def cleanup_old(self, hours: int = 48) -> int:
        """Delete pending asks older than *hours* hours. Returns count deleted."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM pending_asks "
                "WHERE created_at < datetime('now', 'localtime', ? || ' hours')",
                (f"-{hours}",),
            )
            await db.commit()
            return cursor.rowcount
