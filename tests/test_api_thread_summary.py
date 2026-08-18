"""Tests for the running thread-summary API (/api/ingest/summary).

Covers the three handlers plus the prompt-assembly helper:
- GET  (external, token-gated): read stored summary + marker for a diff export.
- POST (internal control plane): the Claude session saves an updated summary.
- DELETE (reset): drop a stored summary.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.database.ingest_repo import IngestResultRepository
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.database.summary_repo import ThreadSummaryRepository
from claude_discord.ext.api_server import ApiServer


@pytest.fixture
def db_path() -> Iterator[str]:
    # A real file (not :memory:) — the repos open a fresh connection per call,
    # and each :memory: connect() would get its own empty database.
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def notif_repo(db_path: str) -> NotificationRepository:
    r = NotificationRepository(db_path)
    await r.init_db()
    return r


@pytest.fixture
async def ingest_repo(db_path: str) -> IngestResultRepository:
    r = IngestResultRepository(db_path)
    await r.init_db()
    return r


@pytest.fixture
async def summary_repo(db_path: str) -> ThreadSummaryRepository:
    r = ThreadSummaryRepository(db_path)
    await r.init_db()
    return r


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock()


@pytest.fixture
def api(
    notif_repo: NotificationRepository,
    ingest_repo: IngestResultRepository,
    summary_repo: ThreadSummaryRepository,
    bot: MagicMock,
) -> ApiServer:
    return ApiServer(
        repo=notif_repo,
        bot=bot,
        ingest_token="secret",
        ingest_repo=ingest_repo,
        summary_repo=summary_repo,
    )


@pytest.fixture
async def client(api: ApiServer) -> TestClient:
    """Internal (localhost) app: has GET + POST + DELETE summary routes."""
    c = TestClient(TestServer(api.app))
    await c.start_server()
    yield c
    await c.close()


@pytest.fixture
async def ext_client(api: ApiServer) -> TestClient:
    """External listener app: only the GET summary route is exposed."""
    c = TestClient(TestServer(api.external_app))
    await c.start_server()
    yield c
    await c.close()


AUTH = {"Authorization": "Bearer secret"}


class TestGetSummary:
    async def test_unknown_key_returns_empty(self, client: TestClient) -> None:
        resp = await client.get("/api/ingest/summary", params={"key": "nope"}, headers=AUTH)
        assert resp.status == 200
        body = await resp.json()
        assert body["exists"] is False
        assert body["summary"] == ""
        assert body["marker"] is None

    async def test_requires_token(self, client: TestClient) -> None:
        resp = await client.get("/api/ingest/summary", params={"key": "k"})
        assert resp.status == 401

    async def test_rejects_wrong_token(self, client: TestClient) -> None:
        resp = await client.get(
            "/api/ingest/summary",
            params={"key": "k"},
            headers={"Authorization": "Bearer nope"},
        )
        assert resp.status == 401

    async def test_missing_key_is_400(self, client: TestClient) -> None:
        resp = await client.get("/api/ingest/summary", headers=AUTH)
        assert resp.status == 400

    async def test_summary_route_not_shadowed_by_result_id(self, client: TestClient) -> None:
        """'summary' must hit the summary handler, not GET /api/ingest/{result_id}."""
        resp = await client.get("/api/ingest/summary", params={"key": "k"}, headers=AUTH)
        assert resp.status == 200
        assert "exists" in await resp.json()


class TestSaveSummary:
    async def test_save_by_key_then_read_back(self, client: TestClient) -> None:
        save = await client.post(
            "/api/ingest/summary",
            json={"key": "teams:1", "summary": "hello world", "marker": "500"},
        )
        assert save.status == 200
        assert (await save.json())["marker"] == "500"

        read = await client.get("/api/ingest/summary", params={"key": "teams:1"}, headers=AUTH)
        body = await read.json()
        assert body["exists"] is True
        assert body["summary"] == "hello world"
        assert body["marker"] == "500"

    async def test_save_is_internal_no_token_needed(self, client: TestClient) -> None:
        # No Authorization header — internal control-plane endpoint.
        resp = await client.post("/api/ingest/summary", json={"key": "teams:2", "summary": "x"})
        assert resp.status == 200

    async def test_save_by_result_id_resolves_key_and_marker(
        self, client: TestClient, ingest_repo: IngestResultRepository
    ) -> None:
        await ingest_repo.create(result_id="rid1", summary_key="teams:3", pending_marker="900")
        resp = await client.post(
            "/api/ingest/summary", json={"result_id": "rid1", "summary": "distilled"}
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["key"] == "teams:3"
        assert body["marker"] == "900"  # advanced from the ingest row, not the session

    async def test_save_unknown_result_id_is_404(self, client: TestClient) -> None:
        resp = await client.post("/api/ingest/summary", json={"result_id": "ghost", "summary": "x"})
        assert resp.status == 404

    async def test_save_requires_summary(self, client: TestClient) -> None:
        resp = await client.post("/api/ingest/summary", json={"key": "k"})
        assert resp.status == 400

    async def test_external_app_has_no_summary_write(self, ext_client: TestClient) -> None:
        # The external listener exposes GET only; POST must not be routed there.
        resp = await ext_client.post("/api/ingest/summary", json={"key": "k", "summary": "x"})
        assert resp.status in (404, 405)


class TestDeleteSummary:
    async def test_delete_then_gone(self, client: TestClient) -> None:
        await client.post("/api/ingest/summary", json={"key": "teams:9", "summary": "s"})
        resp = await client.delete("/api/ingest/summary", params={"key": "teams:9"}, headers=AUTH)
        assert (await resp.json())["status"] == "deleted"
        read = await client.get("/api/ingest/summary", params={"key": "teams:9"}, headers=AUTH)
        assert (await read.json())["exists"] is False


class TestBuildIngestPrompt:
    def test_injects_stored_summary_and_save_instruction(self, api: ApiServer) -> None:
        prompt = api._build_ingest_prompt(
            content="返信して",
            saved_paths=[Path("/tmp/ingest/x/teams-export.md")],
            summary_key="teams:1",
            stored_summary="過去の決定事項ABC",
            result_id="rid42",
        )
        assert "過去の決定事項ABC" in prompt
        assert "これまでの要約" in prompt
        assert "/api/ingest/summary" in prompt
        assert "rid42" in prompt
        assert "teams-export.md" in prompt

    def test_first_run_has_no_stored_block_but_still_asks_to_save(self, api: ApiServer) -> None:
        prompt = api._build_ingest_prompt(
            content="返信して",
            saved_paths=[],
            summary_key="teams:1",
            stored_summary="",
            result_id="rid1",
        )
        assert "===== これまでの要約" not in prompt  # no stored-summary block
        assert "最初の取り込み" in prompt
        assert "/api/ingest/summary" in prompt

    def test_no_summary_key_is_plain_prompt(self, api: ApiServer) -> None:
        prompt = api._build_ingest_prompt(
            content="ふつうの依頼",
            saved_paths=[],
            summary_key=None,
            stored_summary="",
            result_id="rid1",
        )
        assert "要約" not in prompt
        assert "/api/ingest/summary" not in prompt
        assert prompt.strip() == "ふつうの依頼"
