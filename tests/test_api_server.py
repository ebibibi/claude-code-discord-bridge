"""Tests for ApiServer REST API extension."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

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
    async def test_notify_text_format(self, client: TestClient, bot: MagicMock) -> None:
        channel = bot.get_channel.return_value
        resp = await client.post("/api/notify", json={"message": "Hello text!", "format": "text"})
        assert resp.status == 200
        channel.send.assert_called_once_with("Hello text!")

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


class TestNotifyPoll:
    """Tests for poll parameter in /api/notify."""

    @pytest.mark.asyncio
    async def test_notify_with_poll(self, client: TestClient, bot: MagicMock) -> None:
        """Poll object is constructed and passed to channel.send()."""
        channel = bot.get_channel.return_value
        resp = await client.post(
            "/api/notify",
            json={
                "message": "投票してね",
                "poll": {
                    "question": "好きな言語は？",
                    "answers": ["Python", "Go", "Rust"],
                    "duration_hours": 24,
                },
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "sent"
        call_kwargs = channel.send.call_args.kwargs
        assert "poll" in call_kwargs
        poll = call_kwargs["poll"]
        # discord.py may store question as str or PollMedia depending on version
        q = poll.question
        assert (q.text if hasattr(q, "text") else q) == "好きな言語は？"
        assert len(poll.answers) == 3
        assert poll.duration.total_seconds() == 24 * 3600

    @pytest.mark.asyncio
    async def test_notify_poll_with_multiselect(self, client: TestClient, bot: MagicMock) -> None:
        """allow_multiselect flag is passed through."""
        channel = bot.get_channel.return_value
        resp = await client.post(
            "/api/notify",
            json={
                "message": "複数選択OK",
                "poll": {
                    "question": "好きな食べ物は？",
                    "answers": ["寿司", "ラーメン", "カレー"],
                    "duration_hours": 48,
                    "allow_multiselect": True,
                },
            },
        )
        assert resp.status == 200
        poll = channel.send.call_args.kwargs["poll"]
        assert poll.multiple is True

    @pytest.mark.asyncio
    async def test_notify_poll_default_duration(self, client: TestClient, bot: MagicMock) -> None:
        """Default duration is 24 hours when not specified."""
        channel = bot.get_channel.return_value
        resp = await client.post(
            "/api/notify",
            json={
                "message": "デフォルト期間テスト",
                "poll": {
                    "question": "テスト？",
                    "answers": ["はい", "いいえ"],
                },
            },
        )
        assert resp.status == 200
        poll = channel.send.call_args.kwargs["poll"]
        assert poll.duration.total_seconds() == 24 * 3600

    @pytest.mark.asyncio
    async def test_notify_poll_missing_question(self, client: TestClient) -> None:
        """Poll without question returns 400."""
        resp = await client.post(
            "/api/notify",
            json={
                "message": "テスト",
                "poll": {"answers": ["A", "B"]},
            },
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_notify_poll_missing_answers(self, client: TestClient) -> None:
        """Poll without answers returns 400."""
        resp = await client.post(
            "/api/notify",
            json={
                "message": "テスト",
                "poll": {"question": "テスト？"},
            },
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_notify_poll_too_few_answers(self, client: TestClient) -> None:
        """Poll with fewer than 2 answers returns 400."""
        resp = await client.post(
            "/api/notify",
            json={
                "message": "テスト",
                "poll": {"question": "テスト？", "answers": ["ひとつだけ"]},
            },
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_notify_poll_with_emoji_answers(self, client: TestClient, bot: MagicMock) -> None:
        """Answers with emoji objects are supported."""
        channel = bot.get_channel.return_value
        resp = await client.post(
            "/api/notify",
            json={
                "message": "絵文字付き",
                "poll": {
                    "question": "どれがいい？",
                    "answers": [
                        {"text": "Python", "emoji": "🐍"},
                        {"text": "Go", "emoji": "🐹"},
                    ],
                    "duration_hours": 24,
                },
            },
        )
        assert resp.status == 200
        poll = channel.send.call_args.kwargs["poll"]
        assert len(poll.answers) == 2


class TestNotifyThread:
    """Tests for thread_name parameter in /api/notify."""

    @pytest.fixture
    def bot_with_thread(self) -> MagicMock:
        """Bot mock whose channel supports create_thread().

        Simulates ThreadWithMessage (NamedTuple with .thread attribute)
        returned by TextChannel.create_thread() in discord.py v2.
        """
        b = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        thread = MagicMock(spec=["id", "name", "send"])
        thread.id = 111222333
        thread.name = "PR Review"
        thread.send = AsyncMock()
        # Wrap in ThreadWithMessage-like object
        thread_with_msg = MagicMock(spec=["thread", "message"])
        thread_with_msg.thread = thread
        channel.create_thread = AsyncMock(return_value=thread_with_msg)
        b.get_channel.return_value = channel
        return b

    @pytest.fixture
    async def thread_client(
        self, repo: NotificationRepository, bot_with_thread: MagicMock
    ) -> TestClient:
        api = ApiServer(
            repo=repo,
            bot=bot_with_thread,
            default_channel_id=12345,
        )
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_notify_thread_creates_thread_and_sends_text(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """When thread_name is given, creates a thread and sends message as text."""
        channel = bot_with_thread.get_channel.return_value
        thread = channel.create_thread.return_value.thread
        resp = await thread_client.post(
            "/api/notify",
            json={
                "message": "PR #42 needs review",
                "thread_name": "PR Review",
                "format": "text",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "sent"
        assert data["thread_id"] == "111222333"
        channel.create_thread.assert_called_once_with(name="PR Review")
        thread.send.assert_called_once_with("PR #42 needs review")
        # Channel.send should NOT be called — message goes to thread
        channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_thread_with_embed(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """When thread_name + embed format, embed goes to thread."""
        channel = bot_with_thread.get_channel.return_value
        thread = channel.create_thread.return_value.thread
        resp = await thread_client.post(
            "/api/notify",
            json={
                "message": "Summary here",
                "thread_name": "Summary Thread",
                "format": "embed",
            },
        )
        assert resp.status == 200
        channel.create_thread.assert_called_once_with(name="Summary Thread")
        call_kwargs = thread.send.call_args.kwargs
        assert "embed" in call_kwargs
        channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_thread_default_format_is_text(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """When thread_name is given without format, default to text (not embed)."""
        channel = bot_with_thread.get_channel.return_value
        thread = channel.create_thread.return_value.thread
        resp = await thread_client.post(
            "/api/notify",
            json={
                "message": "Auto text",
                "thread_name": "Auto Thread",
            },
        )
        assert resp.status == 200
        thread.send.assert_called_once_with("Auto text")

    @pytest.mark.asyncio
    async def test_notify_without_thread_name_sends_to_channel(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """Without thread_name, behaves as before — sends to channel."""
        channel = bot_with_thread.get_channel.return_value
        resp = await thread_client.post(
            "/api/notify",
            json={"message": "Channel message", "format": "text"},
        )
        assert resp.status == 200
        channel.send.assert_called_once_with("Channel message")
        channel.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_thread_returns_thread_id(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """Response includes thread_id when a thread is created."""
        resp = await thread_client.post(
            "/api/notify",
            json={"message": "test", "thread_name": "Test"},
        )
        data = await resp.json()
        assert data["thread_id"] == "111222333"
        assert data["thread_name"] == "PR Review"

    @pytest.mark.asyncio
    async def test_notify_blank_thread_name_sends_to_channel(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """Whitespace-only thread_name is treated as absent, avoiding Discord 400s."""
        channel = bot_with_thread.get_channel.return_value
        resp = await thread_client.post(
            "/api/notify",
            json={"message": "No thread please", "thread_name": "   "},
        )
        assert resp.status == 200
        channel.create_thread.assert_not_called()
        channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_thread_name_is_trimmed_and_limited_to_discord_max(
        self, thread_client: TestClient, bot_with_thread: MagicMock
    ) -> None:
        """Thread names are normalized before passing them to Discord."""
        channel = bot_with_thread.get_channel.return_value
        raw_name = f"  {'a' * 120}  "
        resp = await thread_client.post(
            "/api/notify",
            json={"message": "Long title", "thread_name": raw_name},
        )
        assert resp.status == 200
        channel.create_thread.assert_called_once_with(name="a" * 100)


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

    @pytest.mark.asyncio
    async def test_token_prefix_is_rejected(self, auth_client: TestClient) -> None:
        """正しいトークンの前方一致（短い部分文字列）でも 401 になること。

        素朴な `==` 比較ではなく `hmac.compare_digest` を使う前提のテスト。
        長さの異なる文字列でも安全に拒否されることを確認する。
        """
        resp = await auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer test-secret-12"},
        )
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_token_longer_is_rejected(self, auth_client: TestClient) -> None:
        resp = await auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer test-secret-123-extra"},
        )
        assert resp.status == 401


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
    async def test_spawn_auto_start_defaults_to_true(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        await spawn_client.post("/api/spawn", json={"prompt": "Hello"})
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs.get("auto_start") is True

    @pytest.mark.asyncio
    async def test_spawn_accepts_payload_over_1mb(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        """A >1MB attachment body must not be 413'd (aiohttp's default body limit
        is 1MB; ApiServer raises client_max_size for base64 payloads)."""
        import base64

        blob = b"\x00" * (2 * 1024 * 1024)  # 2 MB → ~2.7 MB base64
        resp = await spawn_client.post(
            "/api/spawn",
            json={
                "prompt": "big attachment",
                "attachments": [{"filename": "big.bin", "data": base64.b64encode(blob).decode()}],
            },
        )
        assert resp.status == 201
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs["attachments"][0][1] == blob

    @pytest.mark.asyncio
    async def test_spawn_decodes_attachments_and_passes_to_cog(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        import base64

        blob = b"%PDF-1.4 hello"
        resp = await spawn_client.post(
            "/api/spawn",
            json={
                "prompt": "Issue with attachment",
                "attachments": [{"filename": "spec.pdf", "data": base64.b64encode(blob).decode()}],
            },
        )
        assert resp.status == 201
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs.get("attachments") == [("spec.pdf", blob)]

    @pytest.mark.asyncio
    async def test_spawn_without_attachments_passes_none(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        await spawn_client.post("/api/spawn", json={"prompt": "No files"})
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs.get("attachments") is None

    @pytest.mark.asyncio
    async def test_spawn_invalid_base64_attachment_returns_400(
        self, spawn_client: TestClient
    ) -> None:
        resp = await spawn_client.post(
            "/api/spawn",
            json={
                "prompt": "Bad file",
                "attachments": [{"filename": "x.bin", "data": "not!!base64!!"}],
            },
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_spawn_attachments_must_be_a_list(self, spawn_client: TestClient) -> None:
        resp = await spawn_client.post(
            "/api/spawn",
            json={"prompt": "x", "attachments": {"filename": "a"}},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_spawn_sanitizes_attachment_filename(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        import base64

        await spawn_client.post(
            "/api/spawn",
            json={
                "prompt": "traversal",
                "attachments": [
                    {"filename": "../../etc/passwd", "data": base64.b64encode(b"x").decode()}
                ],
            },
        )
        kwargs = mock_cog.spawn_session.call_args.kwargs
        name = kwargs["attachments"][0][0]
        assert "/" not in name and ".." not in name

    @pytest.mark.asyncio
    async def test_spawn_auto_start_false_passed_to_cog(
        self, spawn_client: TestClient, mock_cog: MagicMock
    ) -> None:
        await spawn_client.post(
            "/api/spawn",
            json={"prompt": "Notify only", "auto_start": False},
        )
        kwargs = mock_cog.spawn_session.call_args.kwargs
        assert kwargs.get("auto_start") is False

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


class TestIngest:
    """Tests for POST /api/ingest — authenticated external spawn with attachments."""

    INGEST_TOKEN = "ingest-secret-xyz"
    AUTH = {"Authorization": f"Bearer {INGEST_TOKEN}"}

    @pytest.fixture
    def mock_cog(self) -> MagicMock:
        thread = MagicMock()
        thread.id = 111222333
        thread.name = "Ingested thread"
        cog = MagicMock()
        cog.spawn_session = AsyncMock(return_value=thread)
        return cog

    @pytest.fixture
    def bot_with_text_channel(self, mock_cog: MagicMock) -> MagicMock:
        import discord

        b = MagicMock()
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        b.get_channel.return_value = channel
        b.cogs = {"ClaudeChatCog": mock_cog}
        return b

    @pytest.fixture
    async def ingest_client(
        self,
        repo: NotificationRepository,
        bot_with_text_channel: MagicMock,
        tmp_path,
    ) -> TestClient:
        api = ApiServer(
            repo=repo,
            bot=bot_with_text_channel,
            default_channel_id=12345,
            ingest_token=self.INGEST_TOKEN,
            working_dir=str(tmp_path),
        )
        api._ingest_tmp = str(tmp_path)  # expose for assertions
        server = TestServer(api.app)
        client = TestClient(server)
        client._api = api  # type: ignore[attr-defined]
        await client.start_server()
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_ingest_disabled_without_token(
        self, repo: NotificationRepository, bot_with_text_channel: MagicMock
    ) -> None:
        api = ApiServer(repo=repo, bot=bot_with_text_channel, default_channel_id=12345)
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/ingest", json={"content": "hi"}, headers=self.AUTH)
            assert resp.status == 503
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ingest_missing_auth_returns_401(self, ingest_client: TestClient) -> None:
        resp = await ingest_client.post("/api/ingest", json={"content": "hi"})
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_ingest_wrong_token_returns_401(self, ingest_client: TestClient) -> None:
        resp = await ingest_client.post(
            "/api/ingest",
            json={"content": "hi"},
            headers={"Authorization": "Bearer nope"},
        )
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_ingest_returns_201_with_thread_info(self, ingest_client: TestClient) -> None:
        resp = await ingest_client.post(
            "/api/ingest", json={"content": "Teams thread body"}, headers=self.AUTH
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["status"] == "spawned"
        assert data["thread_id"] == "111222333"
        assert data["attachments_saved"] == 0

    @pytest.mark.asyncio
    async def test_ingest_missing_content_returns_400(self, ingest_client: TestClient) -> None:
        resp = await ingest_client.post("/api/ingest", json={}, headers=self.AUTH)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_ingest_accepts_prompt_alias(
        self, ingest_client: TestClient, mock_cog: MagicMock
    ) -> None:
        resp = await ingest_client.post(
            "/api/ingest", json={"prompt": "Via alias"}, headers=self.AUTH
        )
        assert resp.status == 201
        _channel, prompt = mock_cog.spawn_session.call_args.args
        assert prompt == "Via alias"

    @pytest.mark.asyncio
    async def test_ingest_saves_attachment_and_references_path(
        self, ingest_client: TestClient, mock_cog: MagicMock, tmp_path
    ) -> None:
        import base64

        payload = base64.b64encode(b"hello file").decode()
        resp = await ingest_client.post(
            "/api/ingest",
            json={
                "content": "See attached",
                "attachments": [{"filename": "report.txt", "data": payload}],
            },
            headers=self.AUTH,
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["attachments_saved"] == 1

        # File written under {working_dir}/ingest/**/report.txt with correct bytes
        matches = list(tmp_path.glob("ingest/*/report.txt"))
        assert len(matches) == 1
        assert matches[0].read_bytes() == b"hello file"

        # Saved path is referenced in the prompt passed to spawn_session
        _channel, prompt = mock_cog.spawn_session.call_args.args
        assert "report.txt" in prompt
        assert str(matches[0]) in prompt

    @pytest.mark.asyncio
    async def test_ingest_rejects_path_traversal_filename(
        self, ingest_client: TestClient, tmp_path
    ) -> None:
        import base64

        payload = base64.b64encode(b"x").decode()
        resp = await ingest_client.post(
            "/api/ingest",
            json={
                "content": "evil",
                "attachments": [{"filename": "../../etc/passwd", "data": payload}],
            },
            headers=self.AUTH,
        )
        assert resp.status == 201
        # Nothing written outside the ingest dir; basename sanitised to "passwd"
        assert list(tmp_path.glob("ingest/*/passwd"))
        assert not list(tmp_path.glob("**/etc/passwd"))

    @pytest.mark.asyncio
    async def test_ingest_invalid_base64_returns_400(self, ingest_client: TestClient) -> None:
        resp = await ingest_client.post(
            "/api/ingest",
            json={"content": "x", "attachments": [{"filename": "a.bin", "data": "!!!notb64"}]},
            headers=self.AUTH,
        )
        assert resp.status == 400

    @staticmethod
    def _make_zip(members: dict[str, bytes]) -> str:
        """Build an in-memory zip from {arcname: bytes} and return base64."""
        import base64
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, blob in members.items():
                zf.writestr(name, blob)
        return base64.b64encode(buf.getvalue()).decode()

    @pytest.mark.asyncio
    async def test_ingest_extracts_zip_bundle_and_lists_extracted_files(
        self, ingest_client: TestClient, mock_cog: MagicMock, tmp_path
    ) -> None:
        zip_b64 = self._make_zip({"a.txt": b"alpha", "docs/b.md": b"# beta"})
        resp = await ingest_client.post(
            "/api/ingest",
            json={
                "content": "See bundle",
                "attachments": [{"filename": "bundle.zip", "data": zip_b64}],
            },
            headers=self.AUTH,
        )
        assert resp.status == 201

        # Zip is expanded on disk; its members exist with correct bytes.
        a = list(tmp_path.glob("ingest/*/**/a.txt"))
        b = list(tmp_path.glob("ingest/*/**/b.md"))
        assert len(a) == 1 and a[0].read_bytes() == b"alpha"
        assert len(b) == 1 and b[0].read_bytes() == b"# beta"

        # The zip archive itself is removed after extraction.
        assert not list(tmp_path.glob("ingest/*/bundle.zip"))

        # Prompt references the extracted files (paths only), not the zip name.
        _channel, prompt = mock_cog.spawn_session.call_args.args
        assert "a.txt" in prompt
        assert "b.md" in prompt
        assert "bundle.zip" not in prompt

    @pytest.mark.asyncio
    async def test_ingest_zip_extraction_blocks_zip_slip(
        self, ingest_client: TestClient, tmp_path
    ) -> None:
        zip_b64 = self._make_zip({"../../evil.txt": b"pwned", "ok.txt": b"safe"})
        resp = await ingest_client.post(
            "/api/ingest",
            json={
                "content": "evil zip",
                "attachments": [{"filename": "bundle.zip", "data": zip_b64}],
            },
            headers=self.AUTH,
        )
        assert resp.status == 201
        # Nothing escapes the ingest dir.
        assert not list(tmp_path.glob("**/evil.txt"))


class TestIngestResult:
    """Tests for /api/ingest result capture + GET /api/ingest/{result_id}."""

    INGEST_TOKEN = "ingest-secret-xyz"
    AUTH = {"Authorization": f"Bearer {INGEST_TOKEN}"}

    @pytest.fixture
    def mock_cog(self) -> MagicMock:
        thread = MagicMock()
        thread.id = 111222333
        thread.name = "Ingested thread"
        cog = MagicMock()
        cog.spawn_session = AsyncMock(return_value=thread)
        return cog

    @pytest.fixture
    def bot_with_text_channel(self, mock_cog: MagicMock) -> MagicMock:
        import discord

        b = MagicMock()
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        b.get_channel.return_value = channel
        b.cogs = {"ClaudeChatCog": mock_cog}
        return b

    @pytest.fixture
    async def ingest_repo(self):
        from claude_discord.database.ingest_repo import IngestResultRepository

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        r = IngestResultRepository(path)
        await r.init_db()
        yield r
        os.unlink(path)

    @pytest.fixture
    async def result_client(
        self,
        repo: NotificationRepository,
        bot_with_text_channel: MagicMock,
        ingest_repo,
        tmp_path,
    ) -> TestClient:
        api = ApiServer(
            repo=repo,
            bot=bot_with_text_channel,
            default_channel_id=12345,
            ingest_token=self.INGEST_TOKEN,
            working_dir=str(tmp_path),
            ingest_repo=ingest_repo,
        )
        server = TestServer(api.app)
        client = TestClient(server)
        client._api = api  # type: ignore[attr-defined]
        await client.start_server()
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_post_returns_result_id_when_repo_configured(
        self, result_client: TestClient
    ) -> None:
        resp = await result_client.post("/api/ingest", json={"content": "hello"}, headers=self.AUTH)
        assert resp.status == 201
        data = await resp.json()
        assert "result_id" in data
        assert len(data["result_id"]) > 0

    @pytest.mark.asyncio
    async def test_get_result_running_then_done(
        self, result_client: TestClient, ingest_repo
    ) -> None:
        resp = await result_client.post("/api/ingest", json={"content": "hello"}, headers=self.AUTH)
        result_id = (await resp.json())["result_id"]

        # Immediately after spawn, the result is still being produced.
        poll = await result_client.get(f"/api/ingest/{result_id}", headers=self.AUTH)
        assert poll.status == 200
        running = await poll.json()
        assert running["status"] == "running"
        assert running["thread_id"] == "111222333"

        # Simulate the session finishing and firing the result sink.
        await ingest_repo.set_result(result_id, "the generated answer")

        poll2 = await result_client.get(f"/api/ingest/{result_id}", headers=self.AUTH)
        done = await poll2.json()
        assert done["status"] == "done"
        assert done["result"] == "the generated answer"

    @pytest.mark.asyncio
    async def test_sink_passed_to_spawn_writes_result(
        self, result_client: TestClient, mock_cog: MagicMock, ingest_repo
    ) -> None:
        resp = await result_client.post("/api/ingest", json={"content": "hello"}, headers=self.AUTH)
        result_id = (await resp.json())["result_id"]

        # The handler must pass a result_sink to spawn_session.
        sink = mock_cog.spawn_session.call_args.kwargs["result_sink"]
        assert sink is not None

        # Invoking the sink (as the real session would) persists the answer.
        await sink("answer via sink", None)
        rec = await ingest_repo.get(result_id)
        assert rec["status"] == "done"
        assert rec["result"] == "answer via sink"

        # Error path routes to set_error.
        await sink(None, "kaboom")
        rec2 = await ingest_repo.get(result_id)
        assert rec2["status"] == "error"
        assert rec2["error"] == "kaboom"

    @pytest.mark.asyncio
    async def test_sink_attaches_answer_markdown_to_thread(
        self, result_client: TestClient, mock_cog: MagicMock, ingest_repo
    ) -> None:
        resp = await result_client.post("/api/ingest", json={"content": "hello"}, headers=self.AUTH)
        result_id = (await resp.json())["result_id"]
        sink = mock_cog.spawn_session.call_args.kwargs["result_sink"]

        with patch(
            "claude_discord.ext.api_server.send_file_blobs",
            new_callable=AsyncMock,
        ) as send_file_blobs:
            await sink("answer via sink", None)

        rec = await ingest_repo.get(result_id)
        assert rec["result"] == "answer via sink"
        send_file_blobs.assert_awaited_once()
        thread, blobs = send_file_blobs.await_args.args[:2]
        assert thread.id == 111222333
        assert blobs == [("ccdb-answer.md", b"answer via sink")]

    @pytest.mark.asyncio
    async def test_sink_does_not_attach_on_error(
        self, result_client: TestClient, mock_cog: MagicMock
    ) -> None:
        resp = await result_client.post("/api/ingest", json={"content": "hello"}, headers=self.AUTH)
        assert resp.status == 201
        sink = mock_cog.spawn_session.call_args.kwargs["result_sink"]

        with patch(
            "claude_discord.ext.api_server.send_file_blobs",
            new_callable=AsyncMock,
        ) as send_file_blobs:
            await sink(None, "kaboom")

        send_file_blobs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_unknown_result_404(self, result_client: TestClient) -> None:
        resp = await result_client.get("/api/ingest/does-not-exist", headers=self.AUTH)
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_get_result_requires_auth(self, result_client: TestClient) -> None:
        resp = await result_client.get("/api/ingest/anything")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_get_result_wrong_token_401(self, result_client: TestClient) -> None:
        resp = await result_client.get(
            "/api/ingest/anything", headers={"Authorization": "Bearer nope"}
        )
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_no_result_id_without_repo(
        self,
        repo: NotificationRepository,
        bot_with_text_channel: MagicMock,
        tmp_path,
    ) -> None:
        # No ingest_repo wired → endpoint still works, just no result retrieval.
        api = ApiServer(
            repo=repo,
            bot=bot_with_text_channel,
            default_channel_id=12345,
            ingest_token=self.INGEST_TOKEN,
            working_dir=str(tmp_path),
        )
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/ingest", json={"content": "hello"}, headers=self.AUTH)
            data = await resp.json()
            assert "result_id" not in data
            # GET returns 503 when retrieval isn't configured.
            poll = await client.get("/api/ingest/whatever", headers=self.AUTH)
            assert poll.status == 503
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ingest_pings_and_joins_owner(
        self, repo: NotificationRepository, ingest_repo, tmp_path
    ) -> None:
        """An ingest session auto-joins + @mentions the bot owner on start, and
        pings them again on completion so a long-running result is delivered
        asynchronously over Discord (no foreground poller needed)."""
        import discord

        thread = MagicMock()
        thread.id = 111222333
        thread.name = "MEHJ thread"
        thread.send = AsyncMock()
        thread.add_user = AsyncMock()

        cog = MagicMock()
        cog.spawn_session = AsyncMock(return_value=thread)

        bot = MagicMock()
        bot.owner_id = 999  # configured owner → should be mentioned/added
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        bot.get_channel.return_value = channel
        bot.cogs = {"ClaudeChatCog": cog}

        api = ApiServer(
            repo=repo,
            bot=bot,
            default_channel_id=12345,
            ingest_token=self.INGEST_TOKEN,
            working_dir=str(tmp_path),
            ingest_repo=ingest_repo,
        )
        server = TestServer(api.app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/ingest", json={"content": "hi"}, headers=self.AUTH)
            assert resp.status == 201

            # Owner auto-joined the thread.
            thread.add_user.assert_awaited()

            # Start ping mentions the owner.
            contents = [c.kwargs.get("content", "") for c in thread.send.call_args_list]
            assert any("<@999>" in s and "開始" in s for s in contents)

            # Completion: invoking the captured sink pings the owner again.
            sink = cog.spawn_session.call_args.kwargs["result_sink"]
            await sink("the answer", None)
            contents = [c.kwargs.get("content", "") for c in thread.send.call_args_list]
            assert any("<@999>" in s and "回答ができました" in s for s in contents)
        finally:
            await client.close()
