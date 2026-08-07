"""Tests for absolute one-shot scheduling (``run_at``) and expiry (``until``).

Both exist for the same failure mode: a reminder that outlives its own purpose.
Before ``until``, a repeating task could only be stopped by the session that it
spawned — so a session that crashed left the task nagging forever.
"""

from __future__ import annotations

import time

import pytest

from claude_discord.database.task_repo import TaskRepository

HOUR = 3600


@pytest.fixture
async def repo(tmp_path) -> TaskRepository:
    r = TaskRepository(str(tmp_path / "tasks.db"))
    await r.init_db()
    return r


class TestRunAt:
    async def test_run_at_sets_next_run_exactly(self, repo: TaskRepository) -> None:
        target = time.time() + HOUR
        task_id = await repo.create(
            name="one-shot",
            prompt="p",
            interval_seconds=86400,
            channel_id=1,
            run_at=target,
            one_shot=True,
        )
        task = await repo.get(task_id)
        assert task is not None
        assert task["next_run_at"] == pytest.approx(target, abs=0.01)

    async def test_run_at_beats_run_immediately(self, repo: TaskRepository) -> None:
        """An explicit instant is a stronger statement than the default."""
        target = time.time() + HOUR
        task_id = await repo.create(
            name="one-shot",
            prompt="p",
            interval_seconds=86400,
            channel_id=1,
            run_at=target,
            run_immediately=True,
        )
        task = await repo.get(task_id)
        assert task is not None
        assert task["next_run_at"] == pytest.approx(target, abs=0.01)

    async def test_run_at_task_is_not_due_yet(self, repo: TaskRepository) -> None:
        await repo.create(
            name="one-shot",
            prompt="p",
            interval_seconds=86400,
            channel_id=1,
            run_at=time.time() + HOUR,
        )
        assert await repo.get_due() == []


class TestUntil:
    async def test_until_is_stored(self, repo: TaskRepository) -> None:
        expiry = time.time() + HOUR
        task_id = await repo.create(
            name="expiring", prompt="p", interval_seconds=60, channel_id=1, until=expiry
        )
        task = await repo.get(task_id)
        assert task is not None
        assert task["until"] == pytest.approx(expiry, abs=0.01)

    async def test_until_defaults_to_none(self, repo: TaskRepository) -> None:
        task_id = await repo.create(name="forever", prompt="p", interval_seconds=60, channel_id=1)
        task = await repo.get(task_id)
        assert task is not None
        assert task["until"] is None

    async def test_due_task_past_its_expiry_is_not_returned(self, repo: TaskRepository) -> None:
        await repo.create(
            name="stale",
            prompt="p",
            interval_seconds=60,
            channel_id=1,
            until=time.time() - 1,
        )
        assert await repo.get_due() == []

    async def test_due_task_within_its_expiry_still_runs(self, repo: TaskRepository) -> None:
        await repo.create(
            name="fresh",
            prompt="p",
            interval_seconds=60,
            channel_id=1,
            until=time.time() + HOUR,
        )
        due = await repo.get_due()
        assert [t["name"] for t in due] == ["fresh"]

    async def test_expire_overdue_disables_and_reports_names(self, repo: TaskRepository) -> None:
        """Expired tasks are disabled, not deleted — the record explains itself."""
        await repo.create(
            name="stale", prompt="p", interval_seconds=60, channel_id=1, until=time.time() - 1
        )
        await repo.create(
            name="fresh", prompt="p", interval_seconds=60, channel_id=1, until=time.time() + HOUR
        )
        await repo.create(name="forever", prompt="p", interval_seconds=60, channel_id=1)

        expired = await repo.expire_overdue()

        assert expired == ["stale"]
        remaining = {t["name"]: t["enabled"] for t in await repo.get_all()}
        assert remaining == {"stale": False, "fresh": True, "forever": True}

    async def test_expire_overdue_is_idempotent(self, repo: TaskRepository) -> None:
        await repo.create(
            name="stale", prompt="p", interval_seconds=60, channel_id=1, until=time.time() - 1
        )
        assert await repo.expire_overdue() == ["stale"]
        assert await repo.expire_overdue() == []


class TestMigrationCompatibility:
    async def test_until_column_added_to_a_pre_existing_table(self, tmp_path) -> None:
        """A database created before ``until`` existed must keep working."""
        import aiosqlite

        db_path = str(tmp_path / "legacy.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """CREATE TABLE scheduled_tasks (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL UNIQUE,
                       prompt TEXT NOT NULL,
                       interval_seconds INTEGER NOT NULL,
                       channel_id INTEGER NOT NULL,
                       working_dir TEXT,
                       enabled INTEGER NOT NULL DEFAULT 1,
                       next_run_at REAL NOT NULL,
                       last_run_at REAL,
                       created_at REAL NOT NULL)"""
            )
            await db.execute(
                """INSERT INTO scheduled_tasks
                   (name, prompt, interval_seconds, channel_id, enabled, next_run_at, created_at)
                   VALUES ('legacy', 'p', 60, 1, 1, ?, ?)""",
                (time.time() - 1, time.time()),
            )
            await db.commit()

        repo = TaskRepository(db_path)
        await repo.init_db()

        due = await repo.get_due()
        assert [t["name"] for t in due] == ["legacy"]
        assert due[0]["until"] is None
