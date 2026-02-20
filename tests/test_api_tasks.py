"""Tests for /api/tasks endpoints in ApiServer."""

from __future__ import annotations

import os
import tempfile
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
def bot() -> MagicMock:
    b = MagicMock()
    b.get_channel = MagicMock(return_value=MagicMock())
    return b


@pytest.fixture
async def client(notif_repo, task_repo, bot) -> TestClient:
    api = ApiServer(
        repo=notif_repo,
        bot=bot,
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


class TestTasksCreate:
    async def test_create_task_returns_201(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "github-check",
                "prompt": "Check GitHub Issues",
                "interval_seconds": 3600,
                "channel_id": 12345,
            },
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["status"] == "created"
        assert "id" in data

    async def test_create_task_missing_required_field(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "no-prompt",
                "interval_seconds": 3600,
                "channel_id": 12345,
            },
        )
        assert resp.status == 400

    async def test_create_task_with_working_dir(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "with-dir",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
                "working_dir": "/home/user/project",
            },
        )
        assert resp.status == 201

    async def test_create_duplicate_name_returns_409(self, client: TestClient) -> None:
        payload = {"name": "dup", "prompt": "p", "interval_seconds": 60, "channel_id": 1}
        await client.post("/api/tasks", json=payload)
        resp = await client.post("/api/tasks", json=payload)
        assert resp.status == 409

    async def test_create_invalid_json_returns_400(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks", data="not-json", headers={"Content-Type": "application/json"}
        )
        assert resp.status == 400


class TestTasksList:
    async def test_list_empty(self, client: TestClient) -> None:
        resp = await client.get("/api/tasks")
        assert resp.status == 200
        data = await resp.json()
        assert data["tasks"] == []

    async def test_list_returns_created_tasks(self, client: TestClient) -> None:
        await client.post(
            "/api/tasks",
            json={
                "name": "task-a",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
            },
        )
        await client.post(
            "/api/tasks",
            json={
                "name": "task-b",
                "prompt": "p",
                "interval_seconds": 120,
                "channel_id": 2,
            },
        )
        resp = await client.get("/api/tasks")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["tasks"]) == 2
        names = {t["name"] for t in data["tasks"]}
        assert names == {"task-a", "task-b"}


class TestTasksDelete:
    async def test_delete_existing_task(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "to-delete",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
            },
        )
        task_id = (await resp.json())["id"]
        del_resp = await client.delete(f"/api/tasks/{task_id}")
        assert del_resp.status == 200
        data = await del_resp.json()
        assert data["status"] == "deleted"

    async def test_delete_nonexistent_returns_404(self, client: TestClient) -> None:
        resp = await client.delete("/api/tasks/99999")
        assert resp.status == 404


class TestTasksPatch:
    async def test_disable_task(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "to-disable",
                "prompt": "p",
                "interval_seconds": 60,
                "channel_id": 1,
            },
        )
        task_id = (await resp.json())["id"]
        patch_resp = await client.patch(f"/api/tasks/{task_id}", json={"enabled": False})
        assert patch_resp.status == 200
        data = await patch_resp.json()
        assert data["status"] == "updated"

    async def test_update_prompt(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/tasks",
            json={
                "name": "to-update",
                "prompt": "old prompt",
                "interval_seconds": 60,
                "channel_id": 1,
            },
        )
        task_id = (await resp.json())["id"]
        patch_resp = await client.patch(f"/api/tasks/{task_id}", json={"prompt": "new prompt"})
        assert patch_resp.status == 200

    async def test_patch_nonexistent_returns_404(self, client: TestClient) -> None:
        resp = await client.patch("/api/tasks/99999", json={"enabled": False})
        assert resp.status == 404
