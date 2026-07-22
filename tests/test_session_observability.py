"""Tests for cross-session observability (Phase 1).

Covers:
- session_view.build_session_views() merge/order rules
- ApiServer GET /api/sessions
- ApiServer GET /api/threads/{thread_id}/messages
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.concurrency import ActiveSession, SessionRegistry
from claude_discord.database.lounge_repo import LoungeMessage, LoungeRepository
from claude_discord.database.models import init_db
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.database.repository import SessionRecord, SessionRepository
from claude_discord.ext.api_server import ApiServer
from claude_discord.session_view import build_session_views, latest_lounge_by_thread

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    await init_db(path)
    yield path
    os.unlink(path)


def _record(thread_id: int, *, last_used_at: str, working_dir: str | None = None) -> SessionRecord:
    return SessionRecord(
        thread_id=thread_id,
        session_id=f"sess-{thread_id}",
        working_dir=working_dir,
        model=None,
        origin="discord",
        summary=None,
        created_at="2026-07-22 10:00:00",
        last_used_at=last_used_at,
    )


def _lounge(thread_id: int, message: str, posted_at: str) -> LoungeMessage:
    return LoungeMessage(
        id=None,
        label="tester",
        message=message,
        posted_at=posted_at,
        thread_id=thread_id,
    )


def _fake_message(
    msg_id: int, content: str, *, author: str = "ebi", is_bot: bool = False
) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.author.display_name = author
    msg.author.bot = is_bot
    msg.created_at = datetime(2026, 7, 22, 13, 0, 0, tzinfo=timezone.utc)
    msg.jump_url = f"https://discord.com/channels/1/2/{msg_id}"
    return msg


def _thread_channel(name: str, messages: list[MagicMock]) -> MagicMock:
    """A stand-in for discord.Thread whose history() is an async iterator."""

    channel = MagicMock()
    channel.name = name

    def history(limit: int = 100):
        async def gen():
            for msg in list(reversed(messages))[:limit]:  # Discord: newest first
                yield msg

        return gen()

    channel.history = history
    return channel


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.session_registry = SessionRegistry()
    b.cogs = {}
    b.get_channel.return_value = None
    b.fetch_channel = AsyncMock(side_effect=RuntimeError("Unknown Channel"))
    return b


@pytest.fixture
async def api_client(db_path: str, bot: MagicMock) -> TestClient:
    notif_repo = NotificationRepository(db_path)
    await notif_repo.init_db()
    api = ApiServer(
        repo=notif_repo,
        bot=bot,
        default_channel_id=12345,
        host="127.0.0.1",
        port=0,
        session_repo=SessionRepository(db_path),
        lounge_repo=LoungeRepository(db_path),
    )
    server = TestServer(api.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# build_session_views
# ---------------------------------------------------------------------------


def test_running_sessions_sort_before_idle_ones() -> None:
    views = build_session_views(
        records=[
            _record(1, last_used_at="2026-07-22 13:00:00"),
            _record(2, last_used_at="2026-07-22 12:00:00"),
        ],
        active=[],
        running_thread_ids={2},
        lounge_messages=[],
    )

    assert [v["thread_id"] for v in views] == [2, 1]
    assert views[0]["state"] == "running"
    assert views[1]["state"] == "idle"


def test_registry_only_session_appears_without_db_record() -> None:
    """A session's DB row is written after its first turn — it must still show."""
    views = build_session_views(
        records=[],
        active=[ActiveSession(thread_id=9, description="Fixing the parser", working_dir="/tmp/wt")],
        running_thread_ids={9},
        lounge_messages=[],
    )

    assert len(views) == 1
    assert views[0]["thread_id"] == 9
    assert views[0]["session_id"] is None
    assert views[0]["current_task"] == "Fixing the parser"
    assert views[0]["working_dir"] == "/tmp/wt"


def test_registry_working_dir_overrides_stale_db_value() -> None:
    views = build_session_views(
        records=[_record(5, last_used_at="2026-07-22 12:00:00", working_dir="/home/ebi")],
        active=[
            ActiveSession(thread_id=5, description="worktree work", working_dir="/home/ebi/wt")
        ],
        running_thread_ids=set(),
        lounge_messages=[],
    )

    assert views[0]["working_dir"] == "/home/ebi/wt"


def test_latest_lounge_message_wins_and_threadless_notes_are_ignored() -> None:
    messages = [
        _lounge(1, "starting", "2026-07-22 12:00:00"),
        LoungeMessage(id=None, label="x", message="no thread", posted_at="...", thread_id=None),
        _lounge(1, "halfway", "2026-07-22 12:30:00"),
    ]

    assert latest_lounge_by_thread(messages)[1].message == "halfway"

    views = build_session_views(
        records=[_record(1, last_used_at="2026-07-22 13:00:00")],
        active=[],
        running_thread_ids=set(),
        lounge_messages=messages,
    )
    assert views[0]["latest_lounge"]["message"] == "halfway"


def test_session_without_lounge_note_reports_none() -> None:
    views = build_session_views(
        records=[_record(1, last_used_at="2026-07-22 13:00:00")],
        active=[],
        running_thread_ids=set(),
        lounge_messages=[],
    )

    assert views[0]["latest_lounge"] is None
    assert views[0]["current_task"] is None


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------


async def test_get_sessions_returns_live_and_stored_sessions(
    api_client: TestClient, db_path: str, bot: MagicMock
) -> None:
    await SessionRepository(db_path).save(
        thread_id=111, session_id="s-111", working_dir="/home/ebi"
    )
    await LoungeRepository(db_path).post(message="doing a thing", label="peer", thread_id=111)
    bot.session_registry.register(222, "reviewing a PR", "/home/ebi/wt-222")

    resp = await api_client.get("/api/sessions")
    assert resp.status == 200
    sessions = (await resp.json())["sessions"]

    by_id = {s["thread_id"]: s for s in sessions}
    assert by_id[111]["state"] == "idle"
    assert by_id[111]["latest_lounge"]["message"] == "doing a thing"
    assert by_id[222]["state"] == "running"
    assert by_id[222]["current_task"] == "reviewing a PR"


async def test_get_sessions_filters_by_state_and_excludes_caller(
    api_client: TestClient, db_path: str, bot: MagicMock
) -> None:
    await SessionRepository(db_path).save(thread_id=111, session_id="s-111")
    bot.session_registry.register(222, "busy", None)
    bot.session_registry.register(333, "also busy", None)

    resp = await api_client.get("/api/sessions?state=running&exclude_thread=333")
    assert resp.status == 200
    assert [s["thread_id"] for s in (await resp.json())["sessions"]] == [222]


async def test_get_sessions_rejects_bad_limit(api_client: TestClient) -> None:
    resp = await api_client.get("/api/sessions?limit=abc")
    assert resp.status == 400


async def test_get_sessions_without_session_repo_returns_503(db_path: str, bot: MagicMock) -> None:
    notif_repo = NotificationRepository(db_path)
    await notif_repo.init_db()
    api = ApiServer(repo=notif_repo, bot=bot, host="127.0.0.1", port=0)
    client = TestClient(TestServer(api.app))
    await client.start_server()
    try:
        resp = await client.get("/api/sessions")
        assert resp.status == 503
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# GET /api/threads/{thread_id}/messages
# ---------------------------------------------------------------------------


async def test_get_thread_messages_returns_oldest_first(
    api_client: TestClient, bot: MagicMock
) -> None:
    bot.get_channel.return_value = _thread_channel(
        "peer thread",
        [
            _fake_message(1, "start the work"),
            _fake_message(2, "on it", author="EbiBot", is_bot=True),
        ],
    )

    resp = await api_client.get("/api/threads/777/messages")
    assert resp.status == 200
    body = await resp.json()

    assert body["thread_id"] == 777
    assert body["thread_name"] == "peer thread"
    assert [m["content"] for m in body["messages"]] == ["start the work", "on it"]
    assert body["messages"][1]["is_bot"] is True
    assert body["messages"][0]["created_at"].startswith("2026-07-22T13:00:00")


async def test_get_thread_messages_truncates_long_content(
    api_client: TestClient, bot: MagicMock
) -> None:
    bot.get_channel.return_value = _thread_channel("big", [_fake_message(1, "x" * 5000)])

    body = await (await api_client.get("/api/threads/777/messages")).json()
    assert body["messages"][0]["truncated"] is True
    assert len(body["messages"][0]["content"]) == 2000


async def test_get_thread_messages_honours_limit(api_client: TestClient, bot: MagicMock) -> None:
    bot.get_channel.return_value = _thread_channel(
        "many", [_fake_message(i, f"msg {i}") for i in range(10)]
    )

    body = await (await api_client.get("/api/threads/777/messages?limit=3")).json()
    assert [m["content"] for m in body["messages"]] == ["msg 7", "msg 8", "msg 9"]


async def test_get_thread_messages_unknown_thread_returns_404(
    api_client: TestClient, bot: MagicMock
) -> None:
    resp = await api_client.get("/api/threads/777/messages")
    assert resp.status == 404


async def test_get_thread_messages_rejects_non_numeric_thread_id(
    api_client: TestClient,
) -> None:
    resp = await api_client.get("/api/threads/abc/messages")
    assert resp.status == 400
