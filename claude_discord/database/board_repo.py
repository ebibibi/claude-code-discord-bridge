"""Repository for Project Board items.

The Project Board tracks all ongoing projects, tasks, and initiatives across
the organization. Unlike the AI Lounge (ephemeral chat), board items are
persistent and structured — each has a status, category, blocker info, and
next action.

Claude Code sessions read the board at startup ("what's stuck?") and update
it at completion ("I finished X"). The board is also surfaced to humans via
Discord daily digests and (optionally) an Obsidian vault export.

Messages are stored in the shared SQLite sessions DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# Board items are persistent — no auto-pruning (unlike lounge).
# But we cap the total to prevent abuse.
_MAX_BOARD_ITEMS = 500

BOARD_SCHEMA = """\
CREATE TABLE IF NOT EXISTS board_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'not_started',
    blocker TEXT,
    next_action TEXT,
    priority INTEGER NOT NULL DEFAULT 3,
    wf_id TEXT,
    owner TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_board_status ON board_items(status);
CREATE INDEX IF NOT EXISTS idx_board_category ON board_items(category);
CREATE INDEX IF NOT EXISTS idx_board_priority ON board_items(priority);
"""

# Valid statuses for board items.
VALID_STATUSES = frozenset({
    "not_started",  # 未着手
    "in_progress",  # 進行中
    "blocked",      # 止まってる（待ち or 詰まり）
    "done",         # 完了
    "running",      # 自動稼働中（放っておいてOK）
})

# Valid categories aligned with folder structure.
VALID_CATEGORIES = frozenset({
    "A_listing",     # 出品
    "B_inventory",   # 在庫・発注
    "C_order_cs",    # 受注・CS
    "D_accounting",  # 経理
    "E_data",        # データ基盤
    "F_goq",         # GoQ連携
    "G_crm",         # CRM
    "API",           # API連携（SP-API, MF, Yahoo等）
    "infra",         # インフラ（CCDB, セキュリティ等）
    "other",         # その他
})


@dataclass
class BoardItem:
    """A single project board item."""

    id: int
    title: str
    category: str
    status: str
    blocker: str | None
    next_action: str | None
    priority: int
    wf_id: str | None
    owner: str | None
    created_at: str
    updated_at: str


def _row_to_item(row: aiosqlite.Row) -> BoardItem:
    """Convert a DB row to a BoardItem dataclass."""
    return BoardItem(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        status=row["status"],
        blocker=row["blocker"],
        next_action=row["next_action"],
        priority=row["priority"],
        wf_id=row["wf_id"],
        owner=row["owner"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class BoardRepository:
    """Read/write Project Board items from SQLite.

    All operations use the shared sessions DB so no extra file is needed.
    The table is created via init_db() migration or ensure_schema().
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def ensure_schema(self) -> None:
        """Create the board_items table if it doesn't exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(BOARD_SCHEMA)
            await db.commit()
        logger.info("Board schema ensured")

    async def create(
        self,
        title: str,
        category: str = "other",
        status: str = "not_started",
        blocker: str | None = None,
        next_action: str | None = None,
        priority: int = 3,
        wf_id: str | None = None,
        owner: str | None = None,
    ) -> BoardItem:
        """Insert a new board item and return it."""
        title = (title or "").strip()[:200]  # safety cap
        if not title:
            raise ValueError("title is required")

        if category not in VALID_CATEGORIES:
            category = "other"
        if status not in VALID_STATUSES:
            status = "not_started"
        priority = max(1, min(5, priority))

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            # Check total count
            cur = await db.execute("SELECT COUNT(*) FROM board_items")
            count_row = await cur.fetchone()
            if count_row and count_row[0] >= _MAX_BOARD_ITEMS:
                raise ValueError(f"Board is full ({_MAX_BOARD_ITEMS} items max)")

            cursor = await db.execute(
                "INSERT INTO board_items "
                "(title, category, status, blocker, next_action, priority, wf_id, owner) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, category, status, blocker, next_action, priority, wf_id, owner),
            )
            row_id = cursor.lastrowid
            await db.commit()

            cur = await db.execute(
                "SELECT * FROM board_items WHERE id = ?", (row_id,)
            )
            row = await cur.fetchone()

        if row is None:
            raise RuntimeError(f"Failed to retrieve board item id={row_id}")

        result = _row_to_item(row)
        logger.info("Board item created: %r (id=%d)", title, result.id)
        return result

    async def update(self, item_id: int, **kwargs: Any) -> BoardItem | None:
        """Update a board item by ID. Returns updated item or None if not found.

        Allowed kwargs: title, category, status, blocker, next_action, priority, wf_id, owner.
        """
        allowed = {
            "title", "category", "status", "blocker",
            "next_action", "priority", "wf_id", "owner",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise ValueError("No valid fields to update")

        # Validate specific fields
        if "status" in updates and updates["status"] not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {updates['status']}")
        if "category" in updates and updates["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {updates['category']}")
        if "priority" in updates:
            updates["priority"] = max(1, min(5, int(updates["priority"])))

        # Always update updated_at
        updates["updated_at"] = "datetime('now', 'localtime')"

        set_parts = []
        params: list[Any] = []
        for k, v in updates.items():
            if k == "updated_at":
                set_parts.append("updated_at = datetime('now', 'localtime')")
            else:
                set_parts.append(f"{k} = ?")
                params.append(v)
        params.append(item_id)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                f"UPDATE board_items SET {', '.join(set_parts)} WHERE id = ?",
                params,
            )
            await db.commit()

            cur = await db.execute(
                "SELECT * FROM board_items WHERE id = ?", (item_id,)
            )
            row = await cur.fetchone()

        if row is None:
            return None

        result = _row_to_item(row)
        logger.info("Board item updated: id=%d", item_id)
        return result

    async def delete(self, item_id: int) -> bool:
        """Delete a board item by ID. Returns True if deleted."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM board_items WHERE id = ?", (item_id,)
            )
            await db.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Board item deleted: id=%d", item_id)
        return deleted

    async def get(self, item_id: int) -> BoardItem | None:
        """Get a single board item by ID."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM board_items WHERE id = ?", (item_id,)
            )
            row = await cur.fetchone()

        return _row_to_item(row) if row else None

    async def list(
        self,
        status: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[BoardItem]:
        """List board items with optional filters.

        Args:
            status: Comma-separated statuses to filter (e.g. "blocked,in_progress").
            category: Filter by category.
            limit: Maximum items to return.
        """
        limit = max(1, min(500, limit))
        where_parts: list[str] = []
        params: list[Any] = []

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip() in VALID_STATUSES]
            if statuses:
                placeholders = ",".join("?" * len(statuses))
                where_parts.append(f"status IN ({placeholders})")
                params.extend(statuses)

        if category:
            where_parts.append("category = ?")
            params.append(category)

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                f"SELECT * FROM board_items {where_clause} "
                f"ORDER BY priority ASC, updated_at DESC LIMIT ?",
                params,
            )

        return [_row_to_item(row) for row in rows]

    async def summary(self) -> dict[str, int]:
        """Return count of items per status."""
        async with aiosqlite.connect(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT status, COUNT(*) as cnt FROM board_items GROUP BY status"
            )
        return {row[0]: row[1] for row in rows}

    async def count(self) -> int:
        """Return total number of board items."""
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM board_items")
            row = await cur.fetchone()
        return row[0] if row else 0
