"""Tests for GET /api/search — lightweight thread/conversation lookup.

The endpoint lets a human (via the /search slash command) or another Claude
session find a past thread by keyword, using the persistent per-thread
``summary`` (opening prompt) already stored in the sessions DB. No AI tokens,
no new storage — just a LIKE query plus a Discord deep-link so archived
threads can be reopened.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.database.lounge_repo import LoungeRepository
from claude_discord.database.models import init_db
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.database.repository import SessionRepository
from claude_discord.ext.api_server import ApiServer


@pytest.fixture
async def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    await init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.cogs = {}
    # No cached channels (mirrors archived threads not being in cache), but the
    # bot is in one guild, so deep-links can still be built.
    b.get_channel.return_value = None
    b.fetch_channel = AsyncMock(side_effect=RuntimeError("Unknown Channel"))
    b.guilds = [MagicMock(id=111)]
    return b


@pytest.fixture
async def seeded_repo(db_path: str) -> SessionRepository:
    repo = SessionRepository(db_path)
    await repo.save(
        thread_id=1001,
        session_id="sess-aaa",
        summary="Fix Substack sync failure for the note automation",
        working_dir="/home/ebi",
        origin="discord",
    )
    await repo.save(
        thread_id=1002,
        session_id="sess-bbb",
        summary="Design a lightweight search feature for ccdb threads",
        working_dir="/home/ebi",
        origin="discord",
    )
    await repo.save(
        thread_id=1003,
        session_id="sess-ccc",
        summary="Deploy JAIX dashboard to production",
        working_dir="/home/ebi/infra",
        origin="cli",
    )
    return repo


@pytest.fixture
async def api_client(db_path: str, bot: MagicMock, seeded_repo: SessionRepository) -> TestClient:
    notif_repo = NotificationRepository(db_path)
    await notif_repo.init_db()
    api = ApiServer(
        repo=notif_repo,
        bot=bot,
        default_channel_id=12345,
        host="127.0.0.1",
        port=0,
        session_repo=seeded_repo,
        lounge_repo=LoungeRepository(db_path),
    )
    server = TestServer(api.app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


async def test_search_matches_summary_keyword(api_client: TestClient) -> None:
    resp = await api_client.get("/api/search", params={"q": "substack"})
    assert resp.status == 200
    body = await resp.json()
    assert body["query"] == "substack"
    thread_ids = [r["thread_id"] for r in body["results"]]
    assert thread_ids == [1001]
    hit = body["results"][0]
    assert hit["deep_link"] == "https://discord.com/channels/111/1001"
    assert "Substack" in hit["summary"]


async def test_search_matches_working_dir(api_client: TestClient) -> None:
    resp = await api_client.get("/api/search", params={"q": "infra"})
    body = await resp.json()
    assert [r["thread_id"] for r in body["results"]] == [1003]


async def test_search_origin_filter(api_client: TestClient) -> None:
    resp = await api_client.get("/api/search", params={"q": "home", "origin": "cli"})
    body = await resp.json()
    assert [r["thread_id"] for r in body["results"]] == [1003]


async def test_search_empty_query_is_rejected(api_client: TestClient) -> None:
    resp = await api_client.get("/api/search", params={"q": "  "})
    assert resp.status == 400


async def test_search_no_matches_returns_empty_list(api_client: TestClient) -> None:
    resp = await api_client.get("/api/search", params={"q": "nonexistentzzz"})
    body = await resp.json()
    assert body["results"] == []


async def test_search_limit_is_capped(api_client: TestClient) -> None:
    resp = await api_client.get("/api/search", params={"q": "home", "limit": "99999"})
    assert resp.status == 200
