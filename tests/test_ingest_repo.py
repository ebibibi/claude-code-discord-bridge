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
