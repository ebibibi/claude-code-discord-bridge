"""The ledger mapping a ThreadKey back to a place a message can be posted.

Every other table stores a conversation as a bare integer — ``sessions``,
``pending_asks``, ``resource_claims``, all of them. For Discord that integer is
the thread's snowflake, so "which conversation is 1535820929958027334" answers
itself. For a frontend whose ids are strings it does not: the key is a hash, and
a hash does not run backwards.

Without this table a Teams deployment could look up a session, learn its key,
and still have no way to reply to it. That is the whole reason the table exists.

It also records the *parent* — the channel or team a conversation lives under —
because reopening a conversation, or opening a sibling next to it, needs an
address the surface protocol does not carry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

from claude_code_core.frontend import DISCORD_FRONTEND, ThreadKey, issue_thread_key

logger = logging.getLogger(__name__)

__all__ = ["FrontendThread", "FrontendThreadRepository"]


@dataclass(frozen=True)
class FrontendThread:
    """One conversation, as the platform it lives on knows it."""

    thread_key: ThreadKey
    frontend: str
    external_id: str
    parent_external_id: str | None


class FrontendThreadRepository:
    """CRUD for the ``frontend_threads`` table.

    Every method opens a short-lived connection, matching the other
    repositories in this package.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def register(
        self,
        frontend: str,
        external_id: str,
        *,
        parent_external_id: str | None = None,
    ) -> ThreadKey:
        """Record a conversation and return the key ccdb will know it by.

        Idempotent: a conversation already in the ledger keeps its key, because
        callers register on every resolve and a key that moved would orphan the
        session rows pointing at the old one. A later *parent* is written
        through — that is the address, not the identity, and a conversation can
        legitimately be seen from a channel we had not recorded before.
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT thread_key FROM frontend_threads WHERE frontend = ? AND external_id = ?",
                (frontend, external_id),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                key = int(existing["thread_key"])
                if parent_external_id is not None:
                    await conn.execute(
                        "UPDATE frontend_threads SET parent_external_id = ? WHERE thread_key = ?",
                        (parent_external_id, key),
                    )
                    await conn.commit()
                return key

            taken = await _taken_keys(conn)
            key = issue_thread_key(frontend, external_id, taken=taken)
            await conn.execute(
                "INSERT INTO frontend_threads "
                "(thread_key, frontend, external_id, parent_external_id) VALUES (?, ?, ?, ?)",
                (key, frontend, external_id, parent_external_id),
            )
            await conn.commit()
            logger.debug("Registered %s conversation %s as key %d", frontend, external_id, key)
            return key

    async def resolve(self, thread_key: ThreadKey) -> FrontendThread | None:
        """Find where to post, given the key ccdb stores. None if unknown."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT thread_key, frontend, external_id, parent_external_id "
                "FROM frontend_threads WHERE thread_key = ?",
                (thread_key,),
            )
            row = await cursor.fetchone()
        return _to_record(row) if row is not None else None

    async def key_for(self, frontend: str, external_id: str) -> ThreadKey | None:
        """The reverse lookup: what key did this conversation get, if any."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT thread_key FROM frontend_threads WHERE frontend = ? AND external_id = ?",
                (frontend, external_id),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row is not None else None

    async def backfill_discord(self) -> int:
        """Adopt every existing Discord session into the ledger.

        An upgrade must not leave the threads a deployment has been using for
        months absent from the table that says where to post. Discord keys are
        their own snowflakes, so this is a straight copy and needs no probing.

        Idempotent, and safe to run on every startup.

        Returns:
            How many rows were added this time — zero on every run after the
            first, which is what makes it safe to call unconditionally.
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO frontend_threads (thread_key, frontend, external_id) "
                "SELECT thread_id, ?, CAST(thread_id AS TEXT) FROM sessions",
                (DISCORD_FRONTEND,),
            )
            added = cursor.rowcount or 0
            await conn.commit()
        if added:
            logger.info("Adopted %d existing Discord thread(s) into frontend_threads", added)
        return added


async def _taken_keys(conn: aiosqlite.Connection) -> set[int]:
    """Keys already in use, for collision probing.

    Read in full rather than probed one query at a time: the table holds one
    row per conversation a deployment has ever had, and issuing a key is rare.
    """
    cursor = await conn.execute("SELECT thread_key FROM frontend_threads")
    return {int(row[0]) for row in await cursor.fetchall()}


def _to_record(row: aiosqlite.Row) -> FrontendThread:
    return FrontendThread(
        thread_key=int(row["thread_key"]),
        frontend=str(row["frontend"]),
        external_id=str(row["external_id"]),
        parent_external_id=row["parent_external_id"],
    )
