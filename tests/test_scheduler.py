"""Tests for SchedulerCog."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_discord.cogs.scheduler import SchedulerCog
from claude_discord.database.task_repo import TaskRepository


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.loop = MagicMock()
    return bot


def _make_runner() -> MagicMock:
    runner = MagicMock()
    runner.clone.return_value = runner
    return runner


@pytest.fixture
async def repo(tmp_path) -> TaskRepository:
    r = TaskRepository(str(tmp_path / "tasks.db"))
    await r.init_db()
    return r


@pytest.fixture
def cog(repo: TaskRepository) -> SchedulerCog:
    return SchedulerCog(_make_bot(), _make_runner(), repo=repo)


class TestSchedulerCogInit:
    def test_cog_created(self, repo: TaskRepository) -> None:
        cog = SchedulerCog(_make_bot(), _make_runner(), repo=repo)
        assert cog is not None

    def test_master_loop_not_running_at_init(self, repo: TaskRepository) -> None:
        cog = SchedulerCog(_make_bot(), _make_runner(), repo=repo)
        # loop should not be running before cog_load is called
        assert not cog._master_loop.is_running()


class TestSchedulerCogMasterLoop:
    async def test_no_tasks_does_nothing(self, cog: SchedulerCog) -> None:
        """Master loop with empty DB should complete without errors."""
        with patch(
            "claude_discord.cogs.scheduler.run_claude_in_thread", new_callable=AsyncMock
        ) as mock_run:
            await cog._master_loop()
        mock_run.assert_not_called()

    async def test_future_task_not_run(self, cog: SchedulerCog, repo: TaskRepository) -> None:
        """Tasks with next_run_at in the future should not fire."""
        task_id = await repo.create(name="future", prompt="p", interval_seconds=3600, channel_id=1)
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() + 9999, task_id),
        )
        with patch(
            "claude_discord.cogs.scheduler.run_claude_in_thread", new_callable=AsyncMock
        ) as mock_run:
            await cog._master_loop()
        mock_run.assert_not_called()

    async def test_due_task_triggers_run(self, cog: SchedulerCog, repo: TaskRepository) -> None:
        """Due tasks should cause _run_task to be called via create_task."""
        task_id = await repo.create(
            name="due", prompt="check stuff", interval_seconds=60, channel_id=42
        )
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() - 1, task_id),
        )
        # Patch _run_task directly — create_task wraps a coroutine, so we need
        # to intercept at this level (not run_claude_in_thread) and then yield
        # control so the event loop can execute the spawned task.
        cog._run_task = AsyncMock()
        await cog._master_loop()
        await asyncio.sleep(0)  # yield to let create_task execute

        cog._run_task.assert_called_once()
        called_task = cog._run_task.call_args[0][0]
        assert called_task["prompt"] == "check stuff"

    async def test_due_task_updates_next_run(self, cog: SchedulerCog, repo: TaskRepository) -> None:
        """After firing, next_run_at should be advanced by interval_seconds."""
        task_id = await repo.create(name="tick", prompt="p", interval_seconds=300, channel_id=1)
        before = time.time()
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() - 1, task_id),
        )
        cog._run_task = AsyncMock()
        await cog._master_loop()

        task = await repo.get(task_id)
        assert task is not None
        assert task["next_run_at"] >= before + 300 - 1

    async def test_disabled_task_not_run(self, cog: SchedulerCog, repo: TaskRepository) -> None:
        """Disabled tasks should not fire even if overdue."""
        task_id = await repo.create(name="dis", prompt="p", interval_seconds=60, channel_id=1)
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 0 WHERE id = ?",
            (time.time() - 1, task_id),
        )
        with patch(
            "claude_discord.cogs.scheduler.run_claude_in_thread", new_callable=AsyncMock
        ) as mock_run:
            await cog._master_loop()
        mock_run.assert_not_called()
