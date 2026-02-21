"""Tests for the AI Lounge feature.

Covers:
- LoungeRepository CRUD and pruning
- lounge.build_lounge_prompt() formatting
- ApiServer GET/POST /api/lounge endpoints
- run_claude_in_thread lounge context injection
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.database.lounge_repo import LoungeMessage, LoungeRepository
from claude_discord.database.models import init_db
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.ext.api_server import ApiServer
from claude_discord.lounge import _NO_MESSAGES, build_lounge_prompt

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_path() -> str:
    """Temporary SQLite DB with schema initialized."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    await init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
async def lounge_repo(db_path: str) -> LoungeRepository:
    return LoungeRepository(db_path)


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    b.get_channel.return_value = channel
    return b


@pytest.fixture
async def notif_repo(db_path: str) -> NotificationRepository:
    """NotificationRepository sharing the same DB (simulates real wiring)."""
    # NotificationRepository uses its own table; init_db already ran
    repo = NotificationRepository(db_path)
    await repo.init_db()
    return repo


@pytest.fixture
async def api_client_with_lounge(
    notif_repo: NotificationRepository,
    lounge_repo: LoungeRepository,
    bot: MagicMock,
) -> TestClient:
    api = ApiServer(
        repo=notif_repo,
        bot=bot,
        default_channel_id=12345,
        host="127.0.0.1",
        port=0,
        lounge_repo=lounge_repo,
        lounge_channel_id=99999,
    )
    server = TestServer(api.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.fixture
async def api_client_no_lounge(
    notif_repo: NotificationRepository,
    bot: MagicMock,
) -> TestClient:
    """ApiServer without lounge_repo wired up."""
    api = ApiServer(
        repo=notif_repo,
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


# ---------------------------------------------------------------------------
# LoungeRepository tests
# ---------------------------------------------------------------------------


class TestLoungeRepository:
    async def test_post_and_get_recent(self, lounge_repo: LoungeRepository) -> None:
        msg = await lounge_repo.post("Hello from AI!", label="TestBot")
        assert msg.id > 0
        assert msg.label == "TestBot"
        assert msg.message == "Hello from AI!"
        assert msg.posted_at  # non-empty datetime string

        recent = await lounge_repo.get_recent(limit=10)
        assert len(recent) == 1
        assert recent[0].id == msg.id

    async def test_get_recent_oldest_first(self, lounge_repo: LoungeRepository) -> None:
        """Messages returned in chronological (oldest-first) order."""
        a = await lounge_repo.post("First", label="A")
        b = await lounge_repo.post("Second", label="B")
        c = await lounge_repo.post("Third", label="C")

        recent = await lounge_repo.get_recent(limit=10)
        ids = [m.id for m in recent]
        assert ids == [a.id, b.id, c.id]

    async def test_get_recent_limit(self, lounge_repo: LoungeRepository) -> None:
        for i in range(5):
            await lounge_repo.post(f"msg {i}", label="Bot")

        recent = await lounge_repo.get_recent(limit=3)
        assert len(recent) == 3
        # Should be the 3 newest, in oldest-first order
        assert recent[-1].message == "msg 4"

    async def test_count(self, lounge_repo: LoungeRepository) -> None:
        assert await lounge_repo.count() == 0
        await lounge_repo.post("one")
        await lounge_repo.post("two")
        assert await lounge_repo.count() == 2

    async def test_label_safety_cap(self, lounge_repo: LoungeRepository) -> None:
        """Labels longer than 50 chars are truncated."""
        long_label = "X" * 100
        msg = await lounge_repo.post("hi", label=long_label)
        assert len(msg.label) <= 50

    async def test_message_safety_cap(self, lounge_repo: LoungeRepository) -> None:
        """Messages longer than 1000 chars are truncated."""
        long_msg = "A" * 2000
        msg = await lounge_repo.post(long_msg, label="Bot")
        assert len(msg.message) <= 1000

    async def test_default_label(self, lounge_repo: LoungeRepository) -> None:
        msg = await lounge_repo.post("no label given")
        assert msg.label == "AI"

    async def test_pruning_keeps_max_messages(self, lounge_repo: LoungeRepository) -> None:
        """After exceeding _MAX_STORED_MESSAGES, old messages are pruned."""
        from claude_discord.database.lounge_repo import _MAX_STORED_MESSAGES

        # Insert max + 5 messages
        for i in range(_MAX_STORED_MESSAGES + 5):
            await lounge_repo.post(f"msg {i}", label="Bot")

        count = await lounge_repo.count()
        assert count == _MAX_STORED_MESSAGES


# ---------------------------------------------------------------------------
# build_lounge_prompt tests
# ---------------------------------------------------------------------------


class TestBuildLoungePrompt:
    def test_empty_returns_no_messages_placeholder(self) -> None:
        result = build_lounge_prompt([])
        assert _NO_MESSAGES.strip() in result

    def test_messages_included(self) -> None:
        messages = [
            LoungeMessage(
                id=1, label="BotA", message="Starting work", posted_at="2026-02-21 10:00:00"
            ),
            LoungeMessage(
                id=2, label="BotB", message="Good luck!", posted_at="2026-02-21 10:01:00"
            ),
        ]
        result = build_lounge_prompt(messages)
        assert "BotA" in result
        assert "Starting work" in result
        assert "BotB" in result
        assert "Good luck!" in result

    def test_timestamp_trimmed_to_hhmm(self) -> None:
        messages = [
            LoungeMessage(id=1, label="Bot", message="hi", posted_at="2026-02-21 14:30:00"),
        ]
        result = build_lounge_prompt(messages)
        assert "14:30" in result
        # Full datetime should not appear (seconds stripped)
        assert "14:30:00" not in result

    def test_curl_instructions_included(self) -> None:
        """The prompt always explains how to post a message."""
        result = build_lounge_prompt([])
        assert "curl" in result
        assert "CCDB_API_URL" in result
        assert "/api/lounge" in result


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestLoungeApiEndpoints:
    async def test_get_lounge_empty(self, api_client_with_lounge: TestClient) -> None:
        resp = await api_client_with_lounge.get("/api/lounge")
        assert resp.status == 200
        data = await resp.json()
        assert data["messages"] == []

    async def test_post_and_get_lounge(self, api_client_with_lounge: TestClient) -> None:
        post_resp = await api_client_with_lounge.post(
            "/api/lounge",
            json={"message": "Testing the lounge!", "label": "TestAI"},
        )
        assert post_resp.status == 201
        body = await post_resp.json()
        assert body["status"] == "posted"
        assert body["label"] == "TestAI"
        assert body["message"] == "Testing the lounge!"

        get_resp = await api_client_with_lounge.get("/api/lounge")
        assert get_resp.status == 200
        data = await get_resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["label"] == "TestAI"

    async def test_post_lounge_missing_message(self, api_client_with_lounge: TestClient) -> None:
        resp = await api_client_with_lounge.post("/api/lounge", json={"label": "Bot"})
        assert resp.status == 400
        data = await resp.json()
        assert "message" in data["error"].lower()

    async def test_post_lounge_invalid_json(self, api_client_with_lounge: TestClient) -> None:
        resp = await api_client_with_lounge.post(
            "/api/lounge",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    async def test_get_lounge_limit_param(self, api_client_with_lounge: TestClient) -> None:
        for i in range(5):
            await api_client_with_lounge.post(
                "/api/lounge", json={"message": f"msg {i}", "label": "Bot"}
            )
        resp = await api_client_with_lounge.get("/api/lounge?limit=3")
        data = await resp.json()
        assert len(data["messages"]) == 3

    async def test_get_lounge_limit_capped_at_50(self, api_client_with_lounge: TestClient) -> None:
        """limit > 50 is silently capped."""
        resp = await api_client_with_lounge.get("/api/lounge?limit=999")
        assert resp.status == 200  # no error, just capped

    async def test_get_lounge_invalid_limit(self, api_client_with_lounge: TestClient) -> None:
        resp = await api_client_with_lounge.get("/api/lounge?limit=abc")
        assert resp.status == 400

    async def test_post_lounge_forwards_to_discord(
        self, api_client_with_lounge: TestClient, bot: MagicMock
    ) -> None:
        """Posting a message sends it to the configured lounge Discord channel."""
        resp = await api_client_with_lounge.post(
            "/api/lounge",
            json={"message": "Hello Discord!", "label": "Claude"},
        )
        assert resp.status == 201
        # bot.get_channel should have been called with lounge_channel_id
        bot.get_channel.assert_called_with(99999)
        channel = bot.get_channel.return_value
        channel.send.assert_called_once()
        call_args = channel.send.call_args[0][0]
        assert "Claude" in call_args
        assert "Hello Discord!" in call_args

    async def test_lounge_503_when_not_configured(self, api_client_no_lounge: TestClient) -> None:
        """GET and POST return 503 when lounge_repo is not wired."""
        get_resp = await api_client_no_lounge.get("/api/lounge")
        assert get_resp.status == 503

        post_resp = await api_client_no_lounge.post("/api/lounge", json={"message": "hi"})
        assert post_resp.status == 503


# ---------------------------------------------------------------------------
# run_claude_in_thread lounge injection tests
# ---------------------------------------------------------------------------


class TestRunHelperLoungeInjection:
    """Verify that lounge context is prepended to the prompt when lounge_repo is set."""

    async def test_lounge_context_injected_into_prompt(self) -> None:
        """When lounge_repo has messages, they appear before the user prompt."""
        from claude_discord.cogs._run_helper import run_claude_in_thread

        lounge_repo_mock = AsyncMock(spec=LoungeRepository)
        lounge_repo_mock.get_recent.return_value = [
            LoungeMessage(
                id=1, label="BotX", message="Busy here!", posted_at="2026-02-21 09:00:00"
            ),
        ]

        captured_prompt: list[str] = []

        async def fake_run(prompt: str, session_id: str | None):
            captured_prompt.append(prompt)
            # Yield a minimal result event
            from claude_discord.claude.types import MessageType, StreamEvent

            result = StreamEvent(message_type=MessageType.RESULT)
            result.is_complete = True
            result.session_id = "sess-123"
            yield result

        thread = MagicMock()
        thread.send = AsyncMock(return_value=MagicMock(embeds=[MagicMock(title="T")]))
        thread.id = 42

        runner = MagicMock()
        runner.working_dir = None
        runner.run = fake_run

        await run_claude_in_thread(
            thread=thread,
            runner=runner,
            repo=None,
            prompt="Do something cool",
            session_id=None,
            lounge_repo=lounge_repo_mock,
        )

        assert captured_prompt, "runner.run was not called"
        full_prompt = captured_prompt[0]
        assert "BotX" in full_prompt
        assert "Busy here!" in full_prompt
        assert "Do something cool" in full_prompt
        # Lounge context comes before the user prompt
        assert full_prompt.index("BotX") < full_prompt.index("Do something cool")

    async def test_no_lounge_context_when_repo_is_none(self) -> None:
        """When lounge_repo is None, the prompt is unchanged."""
        from claude_discord.cogs._run_helper import run_claude_in_thread

        captured_prompt: list[str] = []

        async def fake_run(prompt: str, session_id: str | None):
            captured_prompt.append(prompt)
            from claude_discord.claude.types import MessageType, StreamEvent

            result = StreamEvent(message_type=MessageType.RESULT)
            result.is_complete = True
            result.session_id = "sess-456"
            yield result

        thread = MagicMock()
        thread.send = AsyncMock(return_value=MagicMock(embeds=[MagicMock(title="T")]))
        thread.id = 99

        runner = MagicMock()
        runner.working_dir = None
        runner.run = fake_run

        user_prompt = "Plain prompt without lounge"
        await run_claude_in_thread(
            thread=thread,
            runner=runner,
            repo=None,
            prompt=user_prompt,
            session_id=None,
            lounge_repo=None,
        )

        assert captured_prompt
        # Without lounge_repo, the prompt should not be prefixed with lounge invite
        assert "AI LOUNGE" not in captured_prompt[0]
        assert user_prompt in captured_prompt[0]
