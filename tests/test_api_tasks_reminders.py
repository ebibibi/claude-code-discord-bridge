"""Tests for the reminder-shaped parts of /api/tasks: run_at, until, delete-by-name.

A scheduled session knows its own *name* (it is in its prompt) but not its
numeric row id, so retiring itself has to be possible by name.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.database.task_repo import TaskRepository
from claude_discord.ext.api_server import ApiServer


@pytest.fixture
async def notif_repo() -> NotificationRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = NotificationRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


@pytest.fixture
async def task_repo() -> TaskRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = TaskRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


@pytest.fixture
async def client(notif_repo, task_repo) -> TestClient:
    api = ApiServer(
        repo=notif_repo,
        bot=MagicMock(),
        task_repo=task_repo,
        default_channel_id=12345,
        host="127.0.0.1",
        port=0,
    )
    server = TestServer(api.app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


def _iso(**delta: float) -> str:
    return (datetime.now().astimezone() + timedelta(**delta)).isoformat()


class TestRunAt:
    async def test_run_at_schedules_an_absolute_first_run(
        self, client: TestClient, task_repo: TaskRepository
    ) -> None:
        target = datetime.now().astimezone() + timedelta(hours=3)
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "one-shot",
                "prompt": "p",
                "interval_seconds": 86400,
                "channel_id": 1,
                "run_at": target.isoformat(),
                "one_shot": True,
            },
        )
        assert resp.status == 201
        task = await task_repo.get((await resp.json())["id"])
        assert task is not None
        assert task["next_run_at"] == pytest.approx(target.timestamp(), abs=1)

    async def test_run_at_in_the_past_is_rejected(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "stale",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
                "run_at": _iso(hours=-1),
            },
        )
        assert resp.status == 400
        assert "past" in (await resp.json())["error"].lower()

    async def test_unparseable_run_at_is_rejected(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "bad",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
                "run_at": "tonight",
            },
        )
        assert resp.status == 400


class TestUntil:
    async def test_until_is_stored(self, client: TestClient, task_repo: TaskRepository) -> None:
        expiry = datetime.now().astimezone() + timedelta(days=1)
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "expiring",
                "prompt": "p",
                "interval_seconds": 3600,
                "channel_id": 1,
                "until": expiry.isoformat(),
            },
        )
        assert resp.status == 201
        task = await task_repo.get((await resp.json())["id"])
        assert task is not None
        assert task["until"] == pytest.approx(expiry.timestamp(), abs=1)

    async def test_bare_date_expiry_covers_the_whole_day(
        self, client: TestClient, task_repo: TaskRepository
    ) -> None:
        """ "until tomorrow" must include tomorrow, not end at its midnight."""
        tomorrow = (datetime.now().astimezone() + timedelta(days=1)).date().isoformat()
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "expiring-date",
                "prompt": "p",
                "interval_seconds": 3600,
                "channel_id": 1,
                "until": tomorrow,
            },
        )
        assert resp.status == 201
        task = await task_repo.get((await resp.json())["id"])
        assert task is not None
        expiry = datetime.fromtimestamp(task["until"]).astimezone()
        assert (expiry.hour, expiry.minute) == (23, 59)

    async def test_until_in_the_past_is_rejected(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "already-expired",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
                "until": _iso(hours=-1),
            },
        )
        assert resp.status == 400

    async def test_list_exposes_until(self, client: TestClient) -> None:
        await client.post(
            "/api/tasks",
            json={
                "name": "expiring",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
                "until": _iso(days=1),
            },
        )
        tasks = (await (await client.get("/api/tasks")).json())["tasks"]
        assert tasks[0]["until"] is not None


class TestDeleteByName:
    async def test_delete_by_name_removes_the_task(
        self, client: TestClient, task_repo: TaskRepository
    ) -> None:
        await client.post(
            "/api/tasks",
            json={
                "name": "remind-idr-42",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
            },
        )
        resp = await client.delete("/api/tasks/by-name/remind-idr-42")
        assert resp.status == 200
        assert await task_repo.get_all() == []

    async def test_delete_by_unknown_name_is_404(self, client: TestClient) -> None:
        resp = await client.delete("/api/tasks/by-name/never-existed")
        assert resp.status == 404

    async def test_numeric_delete_still_works(self, client: TestClient) -> None:
        """The by-name route must not shadow the existing id route."""
        created = await client.post(
            "/api/tasks",
            json={"name": "byid", "prompt": "p", "interval_seconds": 60, "channel_id": 1},
        )
        task_id = (await created.json())["id"]
        resp = await client.delete(f"/api/tasks/{task_id}")
        assert resp.status == 200


class TestChannelIdFallback:
    async def test_thread_only_registration_uses_the_default_channel(
        self, client: TestClient, task_repo: TaskRepository
    ) -> None:
        """A session knows its own thread, not its parent channel."""
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "self-followup",
                "prompt": "p",
                "interval_seconds": 86400,
                "thread_id": 777,
                "run_at": "2h",
                "one_shot": True,
            },
        )
        assert resp.status == 201
        task = await task_repo.get((await resp.json())["id"])
        assert task is not None
        assert (task["thread_id"], task["channel_id"]) == (777, 12345)

    async def test_no_thread_and_no_channel_is_still_rejected(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={"name": "nowhere", "prompt": "p", "interval_seconds": 60},
        )
        assert resp.status == 400
        assert "channel_id" in (await resp.json())["error"]
