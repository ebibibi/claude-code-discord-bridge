"""Usage tracking repository for Claude Code session costs and token consumption.

Stores per-session usage records (cost, tokens, duration, user) and provides
aggregation queries for daily/monthly summaries and per-user breakdowns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """A single usage record from a completed Claude Code session."""

    id: int
    thread_id: int
    session_id: str | None
    discord_user_id: str | None
    discord_username: str | None
    bot_name: str | None
    model: str | None
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    duration_ms: int | None
    prompt_summary: str | None
    created_at: str


@dataclass
class UsageSummary:
    """Aggregated usage statistics."""

    total_sessions: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_duration_ms: int


@dataclass
class UserUsageSummary:
    """Per-user aggregated usage statistics."""

    discord_user_id: str
    discord_username: str | None
    total_sessions: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_duration_ms: int


USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    session_id TEXT,
    discord_user_id TEXT,
    discord_username TEXT,
    bot_name TEXT,
    model TEXT,
    cost_usd REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    duration_ms INTEGER,
    prompt_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(discord_user_id);
CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_records(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_bot ON usage_records(bot_name);
"""


class UsageRepository:
    """CRUD and aggregation operations for usage records."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def ensure_schema(self) -> None:
        """Create the usage_records table if it doesn't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(USAGE_SCHEMA)
            logger.info("Usage schema ensured at %s", self.db_path)

    async def record(
        self,
        thread_id: int,
        session_id: str | None = None,
        discord_user_id: str | None = None,
        discord_username: str | None = None,
        bot_name: str | None = None,
        model: str | None = None,
        cost_usd: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_creation_tokens: int | None = None,
        duration_ms: int | None = None,
        prompt_summary: str | None = None,
    ) -> int:
        """Insert a new usage record. Returns the row ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO usage_records
                   (thread_id, session_id, discord_user_id, discord_username,
                    bot_name, model, cost_usd, input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens, duration_ms, prompt_summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    thread_id, session_id, discord_user_id, discord_username,
                    bot_name, model, cost_usd, input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens, duration_ms, prompt_summary,
                ),
            )
            await db.commit()
            row_id = cursor.lastrowid
            logger.info(
                "Usage recorded: thread=%d user=%s cost=$%.4f tokens=%d/%d",
                thread_id,
                discord_username or discord_user_id or "unknown",
                cost_usd or 0,
                input_tokens or 0,
                output_tokens or 0,
            )
            return row_id  # type: ignore[return-value]

    async def get_daily_summary(self, date: str | None = None) -> UsageSummary:
        """Get aggregated usage for a specific date (YYYY-MM-DD). Defaults to today."""
        async with aiosqlite.connect(self.db_path) as db:
            if date:
                query = """SELECT
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records WHERE date(created_at) = ?"""
                cursor = await db.execute(query, (date,))
            else:
                query = """SELECT
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records WHERE date(created_at) = date('now', 'localtime')"""
                cursor = await db.execute(query)
            row = await cursor.fetchone()
            return UsageSummary(
                total_sessions=row[0],
                total_cost_usd=row[1],
                total_input_tokens=row[2],
                total_output_tokens=row[3],
                total_duration_ms=row[4],
            )

    async def get_monthly_summary(self, year_month: str | None = None) -> UsageSummary:
        """Get aggregated usage for a month (YYYY-MM). Defaults to current month."""
        async with aiosqlite.connect(self.db_path) as db:
            if year_month:
                query = """SELECT
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records WHERE strftime('%Y-%m', created_at) = ?"""
                cursor = await db.execute(query, (year_month,))
            else:
                query = """SELECT
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', 'localtime')"""
                cursor = await db.execute(query)
            row = await cursor.fetchone()
            return UsageSummary(
                total_sessions=row[0],
                total_cost_usd=row[1],
                total_input_tokens=row[2],
                total_output_tokens=row[3],
                total_duration_ms=row[4],
            )

    async def get_user_summaries(
        self,
        date: str | None = None,
        year_month: str | None = None,
    ) -> list[UserUsageSummary]:
        """Get per-user summaries. Filter by date or month."""
        async with aiosqlite.connect(self.db_path) as db:
            if date:
                query = """SELECT
                    discord_user_id, discord_username,
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records
                WHERE date(created_at) = ? AND discord_user_id IS NOT NULL
                GROUP BY discord_user_id
                ORDER BY cost DESC"""
                cursor = await db.execute(query, (date,))
            elif year_month:
                query = """SELECT
                    discord_user_id, discord_username,
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records
                WHERE strftime('%Y-%m', created_at) = ? AND discord_user_id IS NOT NULL
                GROUP BY discord_user_id
                ORDER BY cost DESC"""
                cursor = await db.execute(query, (year_month,))
            else:
                # Default: today
                query = """SELECT
                    discord_user_id, discord_username,
                    COUNT(*) as cnt,
                    COALESCE(SUM(cost_usd), 0) as cost,
                    COALESCE(SUM(input_tokens), 0) as inp,
                    COALESCE(SUM(output_tokens), 0) as outp,
                    COALESCE(SUM(duration_ms), 0) as dur
                FROM usage_records
                WHERE date(created_at) = date('now', 'localtime') AND discord_user_id IS NOT NULL
                GROUP BY discord_user_id
                ORDER BY cost DESC"""
                cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [
                UserUsageSummary(
                    discord_user_id=row[0],
                    discord_username=row[1],
                    total_sessions=row[2],
                    total_cost_usd=row[3],
                    total_input_tokens=row[4],
                    total_output_tokens=row[5],
                    total_duration_ms=row[6],
                )
                for row in rows
            ]

    async def get_recent(self, limit: int = 20) -> list[UsageRecord]:
        """Get the most recent usage records."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM usage_records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [UsageRecord(**dict(row)) for row in rows]

    async def get_daily_breakdown(self, year_month: str | None = None) -> list[dict]:
        """Get daily cost breakdown for a given month. Returns list of {date, sessions, cost_usd}."""
        async with aiosqlite.connect(self.db_path) as db:
            if year_month:
                query = """SELECT
                    date(created_at) as day,
                    COUNT(*) as sessions,
                    COALESCE(SUM(cost_usd), 0) as cost
                FROM usage_records
                WHERE strftime('%Y-%m', created_at) = ?
                GROUP BY day ORDER BY day"""
                cursor = await db.execute(query, (year_month,))
            else:
                query = """SELECT
                    date(created_at) as day,
                    COUNT(*) as sessions,
                    COALESCE(SUM(cost_usd), 0) as cost
                FROM usage_records
                WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', 'localtime')
                GROUP BY day ORDER BY day"""
                cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [{"date": row[0], "sessions": row[1], "cost_usd": row[2]} for row in rows]
