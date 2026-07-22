"""Tests for advisory resource claims.

Covers:
- ClaimRepository acquire / renew / conflict / release / expiry
- ApiServer POST, GET and DELETE /api/claims
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.concurrency import SessionRegistry
from claude_discord.database.claims_repo import ClaimRepository, normalize_resource
from claude_discord.database.models import init_db
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.ext.api_server import ApiServer

RESOURCE = "repo:ccdb#issue-123"

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


@pytest.fixture
async def claims_repo(db_path: str) -> ClaimRepository:
    return ClaimRepository(db_path)


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.session_registry = SessionRegistry()
    b.cogs = {}
    b.get_channel.return_value = None
    return b


@pytest.fixture
async def api_client(db_path: str, bot: MagicMock) -> TestClient:
    notif_repo = NotificationRepository(db_path)
    await notif_repo.init_db()
    api = ApiServer(
        repo=notif_repo,
        bot=bot,
        host="127.0.0.1",
        port=0,
        claims_repo=ClaimRepository(db_path),
    )
    client = TestClient(TestServer(api.app))
    await client.start_server()
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# ClaimRepository
# ---------------------------------------------------------------------------


async def test_first_claim_is_acquired(claims_repo: ClaimRepository) -> None:
    acquired, claim = await claims_repo.acquire(RESOURCE, 111, note="fixing it")

    assert acquired is True
    assert claim.thread_id == 111
    assert claim.note == "fixing it"


async def test_second_thread_is_refused_and_learns_the_holder(
    claims_repo: ClaimRepository,
) -> None:
    await claims_repo.acquire(RESOURCE, 111, note="fixing it")
    acquired, holder = await claims_repo.acquire(RESOURCE, 222)

    assert acquired is False
    assert holder.thread_id == 111
    assert holder.note == "fixing it"


async def test_holder_can_renew_its_own_claim(claims_repo: ClaimRepository) -> None:
    _, first = await claims_repo.acquire(RESOURCE, 111, ttl_seconds=60, note="first")
    acquired, renewed = await claims_repo.acquire(RESOURCE, 111, ttl_seconds=3600)

    assert acquired is True
    assert renewed.expires_at > first.expires_at
    assert renewed.note == "first"  # a renewal without a note keeps the original


async def test_expired_claim_does_not_block_another_thread(
    claims_repo: ClaimRepository,
) -> None:
    """A session that dies must not pin a resource forever."""
    await claims_repo.acquire(RESOURCE, 111, ttl_seconds=1)
    # Rewrite expiry into the past rather than sleeping.
    import aiosqlite

    async with aiosqlite.connect(claims_repo._db_path) as db:
        await db.execute(
            "UPDATE resource_claims SET expires_at = datetime('now', 'localtime', '-1 hour')"
        )
        await db.commit()

    acquired, claim = await claims_repo.acquire(RESOURCE, 222)
    assert acquired is True
    assert claim.thread_id == 222
    assert await claims_repo.list_active() == [claim]


async def test_release_requires_ownership_unless_forced(
    claims_repo: ClaimRepository,
) -> None:
    await claims_repo.acquire(RESOURCE, 111)

    assert await claims_repo.release(RESOURCE, 222) is False
    assert await claims_repo.release(RESOURCE, 222, force=True) is True
    assert await claims_repo.list_active() == []


async def test_release_all_for_thread(claims_repo: ClaimRepository) -> None:
    await claims_repo.acquire("repo:a", 111)
    await claims_repo.acquire("repo:b", 111)
    await claims_repo.acquire("repo:c", 222)

    assert await claims_repo.release_all_for_thread(111) == 2
    assert [c.resource for c in await claims_repo.list_active()] == ["repo:c"]


def test_resource_names_are_normalized() -> None:
    assert normalize_resource("  Repo:CCDB#Issue-1  ") == "repo:ccdb#issue-1"
    assert normalize_resource("repo:ccdb   file:x") == "repo:ccdb file:x"
    assert normalize_resource(None) == ""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


async def test_post_claim_returns_201_then_409(api_client: TestClient, bot: MagicMock) -> None:
    bot.session_registry.register(111, "fixing issue 123", "/home/ebi")

    first = await api_client.post(
        "/api/claims", json={"resource": RESOURCE, "thread_id": 111, "note": "fixing it"}
    )
    assert first.status == 201
    assert (await first.json())["status"] == "acquired"

    second = await api_client.post("/api/claims", json={"resource": RESOURCE, "thread_id": 222})
    assert second.status == 409
    body = await second.json()
    assert body["status"] == "held"
    assert body["claim"]["thread_id"] == 111
    assert body["claim"]["note"] == "fixing it"
    # The 409 must be actionable: is the holder still alive?
    assert body["claim"]["holder_state"] == "running"


async def test_post_claim_reports_idle_holder(api_client: TestClient) -> None:
    await api_client.post("/api/claims", json={"resource": RESOURCE, "thread_id": 111})
    resp = await api_client.post("/api/claims", json={"resource": RESOURCE, "thread_id": 222})

    assert (await resp.json())["claim"]["holder_state"] == "idle"


async def test_post_claim_matches_regardless_of_case_and_spacing(
    api_client: TestClient,
) -> None:
    await api_client.post("/api/claims", json={"resource": RESOURCE, "thread_id": 111})
    resp = await api_client.post(
        "/api/claims", json={"resource": "  REPO:CCDB#Issue-123 ", "thread_id": 222}
    )

    assert resp.status == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"thread_id": 111},
        {"resource": "   ", "thread_id": 111},
        {"resource": RESOURCE},
        {"resource": RESOURCE, "thread_id": "not-an-int"},
        {"resource": RESOURCE, "thread_id": 111, "ttl_seconds": "soon"},
        {"resource": "x" * 201, "thread_id": 111},
    ],
)
async def test_post_claim_rejects_bad_input(api_client: TestClient, payload: dict) -> None:
    resp = await api_client.post("/api/claims", json=payload)
    assert resp.status == 400


async def test_get_claims_lists_and_filters(api_client: TestClient) -> None:
    await api_client.post("/api/claims", json={"resource": "repo:a", "thread_id": 111})
    await api_client.post("/api/claims", json={"resource": "repo:b", "thread_id": 222})

    all_claims = (await (await api_client.get("/api/claims")).json())["claims"]
    assert {c["resource"] for c in all_claims} == {"repo:a", "repo:b"}

    filtered = (await (await api_client.get("/api/claims?resource=repo:a")).json())["claims"]
    assert [c["thread_id"] for c in filtered] == [111]


async def test_delete_claim_releases_and_frees_the_resource(api_client: TestClient) -> None:
    await api_client.post("/api/claims", json={"resource": "repo:a", "thread_id": 111})

    resp = await api_client.delete("/api/claims?resource=repo:a&thread_id=111")
    assert resp.status == 200

    again = await api_client.post("/api/claims", json={"resource": "repo:a", "thread_id": 222})
    assert again.status == 201


async def test_delete_claim_by_non_holder_is_404_but_force_works(
    api_client: TestClient,
) -> None:
    await api_client.post("/api/claims", json={"resource": "repo:a", "thread_id": 111})

    assert (await api_client.delete("/api/claims?resource=repo:a&thread_id=222")).status == 404
    assert (await api_client.delete("/api/claims?resource=repo:a&force=true")).status == 200


async def test_delete_claim_requires_thread_id_unless_forced(api_client: TestClient) -> None:
    resp = await api_client.delete("/api/claims?resource=repo:a")
    assert resp.status == 400


async def test_claims_endpoints_return_503_without_repo(db_path: str, bot: MagicMock) -> None:
    notif_repo = NotificationRepository(db_path)
    await notif_repo.init_db()
    api = ApiServer(repo=notif_repo, bot=bot, host="127.0.0.1", port=0)
    client = TestClient(TestServer(api.app))
    await client.start_server()
    try:
        assert (await client.get("/api/claims")).status == 503
        assert (await client.post("/api/claims", json={})).status == 503
        assert (await client.delete("/api/claims?resource=x")).status == 503
    finally:
        await client.close()
