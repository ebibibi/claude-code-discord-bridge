"""Tests for IngestResultRepository — /api/ingest result storage."""

from __future__ import annotations

import os
import tempfile

import pytest

from claude_discord.database.ingest_repo import IngestResultRepository


@pytest.fixture
async def repo() -> IngestResultRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = IngestResultRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


@pytest.mark.asyncio
async def test_create_starts_running(repo: IngestResultRepository) -> None:
    rec = await repo.create(result_id="abc")
    assert rec["result_id"] == "abc"
    assert rec["status"] == "running"
    assert rec["result"] is None
    assert rec["error"] is None


@pytest.mark.asyncio
async def test_set_result_marks_done(repo: IngestResultRepository) -> None:
    await repo.create(result_id="abc")
    await repo.set_result("abc", "the final answer")
    rec = await repo.get("abc")
    assert rec is not None
    assert rec["status"] == "done"
    assert rec["result"] == "the final answer"
    assert rec["error"] is None


@pytest.mark.asyncio
async def test_set_error_marks_error(repo: IngestResultRepository) -> None:
    await repo.create(result_id="abc")
    await repo.set_error("abc", "boom")
    rec = await repo.get("abc")
    assert rec is not None
    assert rec["status"] == "error"
    assert rec["error"] == "boom"


@pytest.mark.asyncio
async def test_set_thread_attaches_info(repo: IngestResultRepository) -> None:
    await repo.create(result_id="abc")
    await repo.set_thread("abc", "999888", "My thread")
    rec = await repo.get("abc")
    assert rec is not None
    assert rec["thread_id"] == "999888"
    assert rec["thread_name"] == "My thread"


@pytest.mark.asyncio
async def test_get_unknown_returns_none(repo: IngestResultRepository) -> None:
    assert await repo.get("nope") is None


@pytest.mark.asyncio
async def test_pruning_keeps_recent_only(repo: IngestResultRepository) -> None:
    repo.MAX_STORED_RESULTS = 3
    for i in range(5):
        await repo.create(result_id=f"id-{i}")
    assert await repo.count() == 3
    # Oldest two pruned, newest three survive.
    assert await repo.get("id-0") is None
    assert await repo.get("id-4") is not None


@pytest.mark.asyncio
async def test_create_stores_summary_link(repo: IngestResultRepository) -> None:
    await repo.create(
        result_id="abc", summary_key="teams:thread:42", pending_marker="1700000000000"
    )
    rec = await repo.get("abc")
    assert rec is not None
    assert rec["summary_key"] == "teams:thread:42"
    assert rec["pending_marker"] == "1700000000000"


@pytest.mark.asyncio
async def test_summary_columns_default_null(repo: IngestResultRepository) -> None:
    await repo.create(result_id="abc")
    rec = await repo.get("abc")
    assert rec is not None
    assert rec["summary_key"] is None
    assert rec["pending_marker"] is None


@pytest.mark.asyncio
async def test_init_db_migrates_legacy_table() -> None:
    """A DB created before summary columns existed gains them on init_db()."""
    import aiosqlite

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Simulate a legacy table without the summary columns.
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "CREATE TABLE ingest_results ("
                "result_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'running', "
                "result TEXT, error TEXT, thread_id TEXT, thread_name TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            await db.execute("INSERT INTO ingest_results (result_id) VALUES ('legacy')")
            await db.commit()
        repo = IngestResultRepository(path)
        await repo.init_db()  # should ALTER in the new columns without error
        await repo.create(result_id="new", summary_key="k", pending_marker="m")
        rec = await repo.get("new")
        assert rec is not None
        assert rec["summary_key"] == "k"
        # Legacy row still readable, new columns NULL.
        legacy = await repo.get("legacy")
        assert legacy is not None
        assert legacy["summary_key"] is None
    finally:
        os.unlink(path)
