"""Resource claim repository — advisory locks between concurrent sessions.

Two sessions that start the same task waste each other's work.  The AI Lounge
catches this after the fact (a session reads a note and realises the overlap);
a claim catches it *before* any work happens and without an LLM round trip:
the second session asks for the same resource, gets 409, and steps aside.

Claims are advisory — nothing enforces them at the filesystem or git level.
They are also short-lived: every claim carries a TTL so a session that dies
mid-task cannot lock a resource forever.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

logger = logging.getLogger(__name__)

# A claim is a hint for the next few hours of work, not a lease on a resource.
DEFAULT_TTL_SECONDS = 2 * 60 * 60
MAX_TTL_SECONDS = 24 * 60 * 60
MAX_RESOURCE_LENGTH = 200
MAX_NOTE_LENGTH = 500


@dataclass(frozen=True)
class Claim:
    """A live advisory claim on a named resource."""

    id: int
    resource: str
    thread_id: int
    note: str | None
    created_at: str
    expires_at: str


def normalize_resource(raw: object) -> str:
    """Reduce a caller-supplied resource name to its canonical form.

    Names are free-form strings agreed on by convention (``repo:ccdb``,
    ``repo:ccdb#issue-123``, ``file:claude_discord/bot.py``).  Case and
    surrounding whitespace are not meaningful, so they are normalized away —
    otherwise ``Repo:CCDB`` and ``repo:ccdb`` would be two separate claims on
    the same thing, which defeats the point.
    """
    return " ".join(str(raw or "").split()).lower()


class ClaimRepository:
    """CRUD for the ``resource_claims`` table.

    Every method opens a short-lived connection, matching the other
    repositories in this package.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def acquire(
        self,
        resource: str,
        thread_id: int,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        note: str | None = None,
    ) -> tuple[bool, Claim]:
        """Claim *resource* for *thread_id*, or report who already holds it.

        Re-claiming a resource the caller already holds renews it — a long task
        can extend its own claim without releasing it first (which would open a
        window for another session to grab it).

        Returns:
            ``(True, claim)`` when acquired or renewed, ``(False, holder)``
            when another live thread holds it.
        """
        ttl = max(1, min(MAX_TTL_SECONDS, ttl_seconds))
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # IMMEDIATE takes the write lock up front so two sessions racing for
            # the same resource cannot both read "unclaimed" and both insert.
            await db.execute("BEGIN IMMEDIATE")
            await self._delete_expired(db)

            cursor = await db.execute(
                "SELECT * FROM resource_claims WHERE resource = ?",
                (resource,),
            )
            existing = await cursor.fetchone()
            if existing is not None and existing["thread_id"] != thread_id:
                await db.commit()
                return False, _row_to_claim(existing)

            await db.execute(
                """
                INSERT INTO resource_claims (resource, thread_id, note, expires_at)
                VALUES (?, ?, ?, datetime('now', 'localtime', ?))
                ON CONFLICT(resource) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    note = COALESCE(excluded.note, resource_claims.note),
                    expires_at = excluded.expires_at
                """,
                (resource, thread_id, note, f"+{ttl} seconds"),
            )
            cursor = await db.execute(
                "SELECT * FROM resource_claims WHERE resource = ?",
                (resource,),
            )
            row = await cursor.fetchone()
            await db.commit()

        if row is None:  # pragma: no cover — the INSERT above guarantees a row
            raise RuntimeError(f"Failed to read back claim for {resource!r}")
        return True, _row_to_claim(row)

    async def list_active(self, resource: str | None = None) -> list[Claim]:
        """Return unexpired claims, most recently created first."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await self._delete_expired(db)
            await db.commit()
            sql = "SELECT * FROM resource_claims WHERE expires_at > datetime('now', 'localtime')"
            params: tuple[object, ...] = ()
            if resource is not None:
                sql += " AND resource = ?"
                params = (resource,)
            sql += " ORDER BY created_at DESC, id DESC"
            rows = await db.execute_fetchall(sql, params)
        return [_row_to_claim(row) for row in rows]

    async def release(self, resource: str, thread_id: int, *, force: bool = False) -> bool:
        """Release a claim.

        Only the holder may release its own claim; ``force`` overrides that so a
        session can reclaim a resource pinned by a peer that died (the 409 body
        reports whether the holder is still running, which is how a caller
        decides that forcing is justified).

        Returns:
            True when a row was removed.
        """
        async with aiosqlite.connect(self._db_path) as db:
            if force:
                cursor = await db.execute(
                    "DELETE FROM resource_claims WHERE resource = ?",
                    (resource,),
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM resource_claims WHERE resource = ? AND thread_id = ?",
                    (resource, thread_id),
                )
            await db.commit()
            return cursor.rowcount > 0

    async def release_all_for_thread(self, thread_id: int) -> int:
        """Drop every claim held by a thread.  Returns the number removed."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM resource_claims WHERE thread_id = ?",
                (thread_id,),
            )
            await db.commit()
            return cursor.rowcount

    @staticmethod
    async def _delete_expired(db: aiosqlite.Connection) -> None:
        """Drop claims whose TTL has passed (lazy pruning, no background job)."""
        await db.execute(
            "DELETE FROM resource_claims WHERE expires_at <= datetime('now', 'localtime')"
        )


def _row_to_claim(row: aiosqlite.Row) -> Claim:
    return Claim(
        id=row["id"],
        resource=row["resource"],
        thread_id=row["thread_id"],
        note=row["note"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )
