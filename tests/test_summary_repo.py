"""Tests for ThreadSummaryRepository — running per-thread summary storage."""

from __future__ import annotations

import os
import tempfile

import pytest

from claude_discord.database.summary_repo import ThreadSummaryRepository


@pytest.fixture
async def repo() -> ThreadSummaryRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = ThreadSummaryRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


@pytest.mark.asyncio
async def test_get_unknown_returns_none(repo: ThreadSummaryRepository) -> None:
    assert await repo.get("teams:thread:404") is None


@pytest.mark.asyncio
async def test_upsert_then_get(repo: ThreadSummaryRepository) -> None:
    await repo.upsert("teams:thread:1", summary="first summary", marker="100")
    rec = await repo.get("teams:thread:1")
    assert rec is not None
    assert rec["summary_key"] == "teams:thread:1"
    assert rec["summary"] == "first summary"
    assert rec["marker"] == "100"


@pytest.mark.asyncio
async def test_upsert_overwrites_and_advances_marker(repo: ThreadSummaryRepository) -> None:
    await repo.upsert("teams:thread:1", summary="v1", marker="100")
    await repo.upsert("teams:thread:1", summary="v2", marker="200")
    rec = await repo.get("teams:thread:1")
    assert rec is not None
    assert rec["summary"] == "v2"
    assert rec["marker"] == "200"


@pytest.mark.asyncio
async def test_upsert_without_marker_keeps_previous_marker(repo: ThreadSummaryRepository) -> None:
    """A summary save that omits the marker must not blank out a known marker."""
    await repo.upsert("teams:thread:1", summary="v1", marker="100")
    await repo.upsert("teams:thread:1", summary="v2", marker=None)
    rec = await repo.get("teams:thread:1")
    assert rec is not None
    assert rec["summary"] == "v2"
    assert rec["marker"] == "100"


@pytest.mark.asyncio
async def test_delete_removes_row(repo: ThreadSummaryRepository) -> None:
    await repo.upsert("teams:thread:1", summary="v1", marker="100")
    assert await repo.delete("teams:thread:1") is True
    assert await repo.get("teams:thread:1") is None
    # Deleting a missing key is a no-op that reports False.
    assert await repo.delete("teams:thread:1") is False


@pytest.mark.asyncio
async def test_prune_keeps_most_recent(repo: ThreadSummaryRepository) -> None:
    repo.MAX_STORED_SUMMARIES = 3
    for i in range(5):
        await repo.upsert(f"teams:thread:{i}", summary=f"s{i}", marker=str(i))
    assert await repo.count() == 3
    # Oldest (0, 1) pruned; newest (2,3,4) survive.
    assert await repo.get("teams:thread:0") is None
    assert await repo.get("teams:thread:4") is not None
