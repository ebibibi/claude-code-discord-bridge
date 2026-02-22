"""Tests for TaskRepository — scheduled task CRUD."""

from __future__ import annotations

import time

import pytest

from claude_discord.database.task_repo import TaskRepository


@pytest.fixture
async def repo(tmp_path) -> TaskRepository:
    r = TaskRepository(str(tmp_path / "tasks.db"))
    await r.init_db()
    return r


class TestTaskRepoCreate:
    async def test_create_returns_id(self, repo: TaskRepository) -> None:
        task_id = await repo.create(
            name="test-task",
            prompt="Do something",
            interval_seconds=3600,
            channel_id=123,
        )
        assert isinstance(task_id, int)
        assert task_id > 0

    async def test_create_sets_next_run_at(self, repo: TaskRepository) -> None:
        before = time.time()
        task_id = await repo.create(
            name="test-task",
            prompt="Do something",
            interval_seconds=3600,
            channel_id=123,
        )
        task = await repo.get(task_id)
        assert task is not None
        assert task["next_run_at"] >= before

    async def test_create_defaults(self, repo: TaskRepository) -> None:
        task_id = await repo.create(
            name="minimal",
            prompt="Minimal prompt",
            interval_seconds=60,
            channel_id=999,
        )
        task = await repo.get(task_id)
        assert task is not None
        assert task["enabled"] is True
        assert task["working_dir"] is None
        assert task["last_run_at"] is None

    async def test_create_with_working_dir(self, repo: TaskRepository) -> None:
        task_id = await repo.create(
            name="with-dir",
            prompt="prompt",
            interval_seconds=60,
            channel_id=1,
            working_dir="/home/user/project",
        )
        task = await repo.get(task_id)
        assert task is not None
        assert task["working_dir"] == "/home/user/project"

    async def test_duplicate_name_raises(self, repo: TaskRepository) -> None:
        import aiosqlite

        await repo.create(name="dup", prompt="p", interval_seconds=60, channel_id=1)
        with pytest.raises(aiosqlite.IntegrityError):
            await repo.create(name="dup", prompt="p2", interval_seconds=60, channel_id=2)


class TestTaskRepoGetAll:
    async def test_get_all_empty(self, repo: TaskRepository) -> None:
        tasks = await repo.get_all()
        assert tasks == []

    async def test_get_all_returns_all(self, repo: TaskRepository) -> None:
        await repo.create(name="a", prompt="p", interval_seconds=60, channel_id=1)
        await repo.create(name="b", prompt="p", interval_seconds=120, channel_id=2)
        tasks = await repo.get_all()
        assert len(tasks) == 2
        names = {t["name"] for t in tasks}
        assert names == {"a", "b"}

    async def test_get_all_includes_disabled(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="x", prompt="p", interval_seconds=60, channel_id=1)
        await repo.set_enabled(task_id, enabled=False)
        tasks = await repo.get_all()
        assert len(tasks) == 1
        assert tasks[0]["enabled"] is False


class TestTaskRepoDue:
    async def test_get_due_empty_when_all_future(self, repo: TaskRepository) -> None:
        await repo.create(name="future", prompt="p", interval_seconds=3600, channel_id=1)
        # Push next_run_at far into the future
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE name = 'future'",
            (time.time() + 9999,),
        )
        due = await repo.get_due()
        assert due == []

    async def test_get_due_returns_overdue_tasks(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="overdue", prompt="p", interval_seconds=60, channel_id=1)
        # Set next_run_at to the past
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() - 100, task_id),
        )
        due = await repo.get_due()
        assert len(due) == 1
        assert due[0]["name"] == "overdue"

    async def test_get_due_excludes_disabled(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="disabled", prompt="p", interval_seconds=60, channel_id=1)
        await repo._db_execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() - 100, task_id),
        )
        await repo.set_enabled(task_id, enabled=False)
        due = await repo.get_due()
        assert due == []


class TestTaskRepoUpdateNextRun:
    async def test_update_next_run_advances_time(self, repo: TaskRepository) -> None:
        before = time.time()
        task_id = await repo.create(name="t", prompt="p", interval_seconds=3600, channel_id=1)
        await repo.update_next_run(task_id, interval_seconds=3600)
        task = await repo.get(task_id)
        assert task is not None
        assert task["next_run_at"] >= before + 3600 - 1  # allow 1s skew
        assert task["last_run_at"] is not None


class TestTaskRepoDelete:
    async def test_delete_existing(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="del", prompt="p", interval_seconds=60, channel_id=1)
        deleted = await repo.delete(task_id)
        assert deleted is True
        assert await repo.get(task_id) is None

    async def test_delete_nonexistent_returns_false(self, repo: TaskRepository) -> None:
        deleted = await repo.delete(99999)
        assert deleted is False


class TestTaskRepoSetEnabled:
    async def test_disable_task(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="e", prompt="p", interval_seconds=60, channel_id=1)
        result = await repo.set_enabled(task_id, enabled=False)
        assert result is True
        task = await repo.get(task_id)
        assert task is not None
        assert task["enabled"] is False

    async def test_enable_task(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="e2", prompt="p", interval_seconds=60, channel_id=1)
        await repo.set_enabled(task_id, enabled=False)
        result = await repo.set_enabled(task_id, enabled=True)
        assert result is True
        task = await repo.get(task_id)
        assert task is not None
        assert task["enabled"] is True

    async def test_enable_nonexistent_returns_false(self, repo: TaskRepository) -> None:
        result = await repo.set_enabled(99999, enabled=True)
        assert result is False


class TestTaskRepoUpdate:
    async def test_update_prompt(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="u", prompt="old", interval_seconds=60, channel_id=1)
        result = await repo.update(task_id, prompt="new prompt")
        assert result is True
        task = await repo.get(task_id)
        assert task is not None
        assert task["prompt"] == "new prompt"

    async def test_update_interval(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="u2", prompt="p", interval_seconds=60, channel_id=1)
        await repo.update(task_id, interval_seconds=7200)
        task = await repo.get(task_id)
        assert task is not None
        assert task["interval_seconds"] == 7200

    async def test_update_nonexistent_returns_false(self, repo: TaskRepository) -> None:
        result = await repo.update(99999, prompt="x")
        assert result is False
