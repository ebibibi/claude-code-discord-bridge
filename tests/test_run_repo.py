"""Tests for RunRepository — async one-shot AI run job storage."""

from __future__ import annotations

import os
import tempfile

import pytest

from claude_discord.database.run_repo import RunRepository


@pytest.fixture
async def run_repo() -> RunRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = RunRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


class TestRunRepositoryCreate:
    async def test_create_returns_running_record(self, run_repo: RunRepository) -> None:
        rec = await run_repo.create(run_id="abc123", backend="claude", model="sonnet")
        assert rec["run_id"] == "abc123"
        assert rec["status"] == "running"
        assert rec["backend"] == "claude"
        assert rec["model"] == "sonnet"
        assert rec["result"] is None
        assert rec["error"] is None

    async def test_get_returns_created_record(self, run_repo: RunRepository) -> None:
        await run_repo.create(run_id="r1", backend="codex", model="gpt-5.4")
        rec = await run_repo.get("r1")
        assert rec is not None
        assert rec["backend"] == "codex"
        assert rec["status"] == "running"

    async def test_get_unknown_returns_none(self, run_repo: RunRepository) -> None:
        assert await run_repo.get("does-not-exist") is None


class TestRunRepositoryComplete:
    async def test_set_result_marks_done(self, run_repo: RunRepository) -> None:
        await run_repo.create(run_id="r1", backend="claude", model="sonnet")
        await run_repo.set_result("r1", "the draft text")
        rec = await run_repo.get("r1")
        assert rec is not None
        assert rec["status"] == "done"
        assert rec["result"] == "the draft text"
        assert rec["error"] is None

    async def test_set_error_marks_error(self, run_repo: RunRepository) -> None:
        await run_repo.create(run_id="r1", backend="claude", model="sonnet")
        await run_repo.set_error("r1", "boom")
        rec = await run_repo.get("r1")
        assert rec is not None
        assert rec["status"] == "error"
        assert rec["error"] == "boom"
        assert rec["result"] is None

    async def test_prune_keeps_table_bounded(self, run_repo: RunRepository) -> None:
        # Create more than the retention cap and ensure old rows are pruned.
        for i in range(run_repo.MAX_STORED_RUNS + 10):
            await run_repo.create(run_id=f"r{i}", backend="claude", model="sonnet")
        count = await run_repo.count()
        assert count <= run_repo.MAX_STORED_RUNS
