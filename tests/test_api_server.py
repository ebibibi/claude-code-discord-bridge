"""Tests for ApiServer REST API extension."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.ext.api_server import ApiServer


@pytest.fixture
async def repo() -> NotificationRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = NotificationRepository(path)
    await repo.init_db()
    yield repo
    os.unlink(path)


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    b.get_channel.return_value = channel
    return b


@pytest.fixture
async def client(repo: NotificationRepository, bot: MagicMock) -> TestClient:
    api = ApiServer(
        repo=repo,
        bot=bot,
        default_channel_id=12345,
        host="127.0.0.1",
        port=0,
    )
    server = TestServer(api.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.fixture
async def auth_client(repo: NotificationRepository, bot: MagicMock) -> TestClient:
    api = ApiServer(
        repo=repo,
        bot=bot,
        default_channel_id=12345,
        api_secret="test-secret-123",
    )
    server = TestServer(api.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client: TestClient) -> None:
        resp = await client.get("/api/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data


class TestNotify:
    @pytest.mark.asyncio
    async def test_notify_sends_message(self, client: TestClient, bot: MagicMock) -> None:
        resp = await client.post("/api/notify", json={"message": "Hello!"})
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "sent"
        bot.get_channel.assert_called_with(12345)

    @pytest.mark.asyncio
    async def test_notify_missing_message(self, client: TestClient) -> None:
        resp = await client.post("/api/notify", json={})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_notify_invalid_json(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/notify",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_notify_no_channel(self, repo: NotificationRepository) -> None:
        bot = MagicMock()
        api = ApiServer(repo=repo, bot=bot, default_channel_id=None)
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/notify", json={"message": "test"})
            assert resp.status == 400
        finally:
            await client.close()


class TestSchedule:
    @pytest.mark.asyncio
    async def test_schedule_creates_notification(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/schedule",
            json={
                "message": "Reminder",
                "scheduled_at": "2026-01-01T09:00:00",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "scheduled"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_schedule_missing_message(self, client: TestClient) -> None:
        resp = await client.post("/api/schedule", json={"scheduled_at": "2026-01-01T09:00:00"})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_schedule_missing_time(self, client: TestClient) -> None:
        resp = await client.post("/api/schedule", json={"message": "test"})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_schedule_invalid_time(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/schedule",
            json={
                "message": "test",
                "scheduled_at": "not-a-date",
            },
        )
        assert resp.status == 400


class TestListScheduled:
    @pytest.mark.asyncio
    async def test_list_empty(self, client: TestClient) -> None:
        resp = await client.get("/api/scheduled")
        assert resp.status == 200
        data = await resp.json()
        assert data["notifications"] == []

    @pytest.mark.asyncio
    async def test_list_after_schedule(self, client: TestClient) -> None:
        await client.post(
            "/api/schedule",
            json={
                "message": "test",
                "scheduled_at": "2026-01-01T09:00:00",
            },
        )
        resp = await client.get("/api/scheduled")
        data = await resp.json()
        assert len(data["notifications"]) == 1


class TestCancelScheduled:
    @pytest.mark.asyncio
    async def test_cancel_existing(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/schedule",
            json={
                "message": "test",
                "scheduled_at": "2026-01-01T09:00:00",
            },
        )
        nid = (await resp.json())["id"]
        resp = await client.delete(f"/api/scheduled/{nid}")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, client: TestClient) -> None:
        resp = await client.delete("/api/scheduled/99999")
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_cancel_invalid_id(self, client: TestClient) -> None:
        resp = await client.delete("/api/scheduled/abc")
        assert resp.status == 400


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_health_bypasses_auth(self, auth_client: TestClient) -> None:
        resp = await auth_client.get("/api/health")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, auth_client: TestClient) -> None:
        resp = await auth_client.post("/api/notify", json={"message": "test"})
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_invalid_token(self, auth_client: TestClient) -> None:
        resp = await auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_valid_token(self, auth_client: TestClient, bot: MagicMock) -> None:
        resp = await auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer test-secret-123"},
        )
        assert resp.status == 200


class TestSpawn:
    """Tests for POST /api/spawn — programmatic Claude session creation."""

    @pytest.fixture
    def mock_cog(self) -> MagicMock:
        """Mock ClaudeChatCog with a spawn_session that returns a fake thread."""
        thread = MagicMock()
        thread.id = 999888777
        thread.name = "Test thread"
        cog = MagicMock()
        cog.spawn_session = AsyncMock(return_value=thread)
        return cog

    @pytest.fixture
    def bot_with_text_channel(self) -> MagicMock:
        """Bot mock whose get_channel() returns a discord.TextChannel spec mock."""
        import discord

        b = MagicMock()
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        b.get_channel.return_value = channel
        return b

    @pytest.fixture
    async def spawn_client(
        self,
        repo: NotificationRepository,
        bot_with_text_channel: MagicMock,
        mock_cog: MagicMock,
    ) -> TestClient:
        """ApiServer client with ClaudeChatCog pre-loaded in bot.cogs."""
        bot_with_text_channel.cogs = {"ClaudeChatCog": mock_cog}
        api = ApiServer(repo=repo, bot=bot_with_text_channel, default_channel_id=12345)
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_spawn_returns_201_with_thread_info(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        resp = await spawn_client.post("/api/spawn", json={"prompt": "Do something useful"})
        assert resp.status == 201
        data = await resp.json()
        assert data["status"] == "spawned"
        assert data["thread_id"] == "999888777"
        assert data["thread_name"] == "Test thread"

    @pytest.mark.asyncio
    async def test_spawn_passes_prompt_to_cog(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        await spawn_client.post("/api/spawn", json={"prompt": "Organise Todoist inbox"})
        mock_cog.spawn_session.assert_called_once()
        _channel, prompt = mock_cog.spawn_session.call_args.args
        assert prompt == "Organise Todoist inbox"

    @pytest.mark.asyncio
    async def test_spawn_passes_thread_name_when_given(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        await spawn_client.post(
            "/api/spawn",
            json={"prompt": "Long prompt", "thread_name": "Custom title"},
        )
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs.get("thread_name") == "Custom title"

    @pytest.mark.asyncio
    async def test_spawn_thread_name_defaults_to_none(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        await spawn_client.post("/api/spawn", json={"prompt": "Some prompt"})
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs.get("thread_name") is None

    @pytest.mark.asyncio
    async def test_spawn_missing_prompt_returns_400(self, spawn_client: TestClient) -> None:
        resp = await spawn_client.post("/api/spawn", json={})
        assert resp.status == 400
        data = await resp.json()
        assert "prompt" in data["error"]

    @pytest.mark.asyncio
    async def test_spawn_empty_prompt_returns_400(self, spawn_client: TestClient) -> None:
        resp = await spawn_client.post("/api/spawn", json={"prompt": "   "})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_spawn_without_cog_returns_503(
        self, repo: NotificationRepository, bot: MagicMock
    ) -> None:
        bot.cogs = {}  # No ClaudeChatCog loaded
        api = ApiServer(repo=repo, bot=bot, default_channel_id=12345)
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/spawn", json={"prompt": "Hello"})
            assert resp.status == 503
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_spawn_no_channel_returns_400(
        self, repo: NotificationRepository, mock_cog: MagicMock
    ) -> None:
        bot = MagicMock()
        bot.cogs = {"ClaudeChatCog": mock_cog}
        # No default_channel_id, no channel_id in body
        api = ApiServer(repo=repo, bot=bot, default_channel_id=None)
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/spawn", json={"prompt": "Hello"})
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_spawn_invalid_json_returns_400(self, spawn_client: TestClient) -> None:
        resp = await spawn_client.post(
            "/api/spawn",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400


class TestMarkResume:
    """Tests for POST /api/mark-resume endpoint."""

    @pytest.fixture
    async def resume_client(self, repo: NotificationRepository, bot: MagicMock) -> TestClient:
        import os
        import tempfile

        from claude_discord.database.models import init_db as _init
        from claude_discord.database.resume_repo import PendingResumeRepository

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        await _init(path)
        resume_repo = PendingResumeRepository(path)

        api = ApiServer(repo=repo, bot=bot, default_channel_id=12345, resume_repo=resume_repo)
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        yield client
        await client.close()
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_mark_resume_returns_201(self, resume_client: TestClient) -> None:
        resp = await resume_client.post("/api/mark-resume", json={"thread_id": 123456789})
        assert resp.status == 201
        data = await resp.json()
        assert data["status"] == "marked"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_mark_resume_with_all_fields(self, resume_client: TestClient) -> None:
        resp = await resume_client.post(
            "/api/mark-resume",
            json={
                "thread_id": 987654321,
                "session_id": "abc-123",
                "reason": "self_restart",
                "resume_prompt": "Please continue the previous task.",
            },
        )
        assert resp.status == 201

    @pytest.mark.asyncio
    async def test_mark_resume_missing_thread_id_returns_400(
        self, resume_client: TestClient
    ) -> None:
        resp = await resume_client.post("/api/mark-resume", json={})
        assert resp.status == 400
        data = await resp.json()
        assert "thread_id" in data["error"]

    @pytest.mark.asyncio
    async def test_mark_resume_invalid_thread_id_returns_400(
        self, resume_client: TestClient
    ) -> None:
        resp = await resume_client.post("/api/mark-resume", json={"thread_id": "not-a-number"})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_mark_resume_without_repo_returns_503(
        self, repo: NotificationRepository, bot: MagicMock
    ) -> None:
        api = ApiServer(repo=repo, bot=bot, default_channel_id=12345)  # no resume_repo
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/mark-resume", json={"thread_id": 111})
            assert resp.status == 503
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_mark_resume_invalid_json_returns_400(self, resume_client: TestClient) -> None:
        resp = await resume_client.post(
            "/api/mark-resume",
            data=b"bad",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
