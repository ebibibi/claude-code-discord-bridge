"""Tests for /api/run endpoints in ApiServer (async one-shot AI job)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from claude_discord.claude.types import MessageType, StreamEvent
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.database.run_repo import RunRepository
from claude_discord.ext.api_server import ApiServer

from .conftest import make_async_gen


# --------------------------------------------------------------------------
# Fakes — engine-neutral backend/factory/settings doubles
# --------------------------------------------------------------------------
class _FakeBackend:
    def __init__(self, events: list[StreamEvent]) -> None:
        self.run = make_async_gen(events)
        self.clone_kwargs: dict | None = None

    def clone(self, **kwargs: object):
        self.clone_kwargs = kwargs
        return self


class _FakeFactory:
    """Records the backend/model it was asked to build."""

    def __init__(self, events: list[StreamEvent]) -> None:
        self._events = events
        self.built: list[dict] = []
        self.last_backend = _FakeBackend(events)

    def default_model_for(self, backend: str) -> str:
        return {"claude": "sonnet", "codex": "gpt-5.4"}.get(backend, "sonnet")

    def build(self, *, backend: str, model: str, thread_id: int | None = None) -> _FakeBackend:
        self.built.append({"backend": backend, "model": model})
        self.last_backend = _FakeBackend(self._events)
        return self.last_backend


class _FakeSettings:
    def __init__(self, backend: str = "claude") -> None:
        self._backend = backend

    async def current_backend(self, thread_id: int | None = None) -> str:
        return self._backend

    async def current_model(self, backend: str, thread_id: int | None = None) -> str | None:
        return None


_RESULT_EVENTS = [
    StreamEvent(message_type=MessageType.SYSTEM, session_id="s"),
    StreamEvent(message_type=MessageType.RESULT, is_complete=True, text="generated draft"),
]


@pytest.fixture
async def notif_repo() -> NotificationRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = NotificationRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


@pytest.fixture
async def run_repo() -> RunRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = RunRepository(path)
    await r.init_db()
    yield r
    os.unlink(path)


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock()


@pytest.fixture
def factory() -> _FakeFactory:
    return _FakeFactory(_RESULT_EVENTS)


@pytest.fixture
async def client(notif_repo, run_repo, factory, bot) -> TestClient:
    api = ApiServer(
        repo=notif_repo,
        bot=bot,
        run_repo=run_repo,
        backend_factory=factory,
        backend_settings=_FakeSettings(),
        host="127.0.0.1",
        port=0,
    )
    server = TestServer(api.app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


async def _poll_until_done(client: TestClient, run_id: str, tries: int = 50) -> dict:
    for _ in range(tries):
        resp = await client.get(f"/api/run/{run_id}")
        data = await resp.json()
        if data["status"] != "running":
            return data
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish")


class TestRunCreate:
    async def test_create_returns_201_with_run_id(self, client: TestClient) -> None:
        resp = await client.post("/api/run", json={"prompt": "hello"})
        assert resp.status == 201
        data = await resp.json()
        assert data["status"] == "running"
        assert "run_id" in data
        assert data["backend"] == "claude"
        assert data["model"] == "sonnet"

    async def test_missing_prompt_returns_400(self, client: TestClient) -> None:
        resp = await client.post("/api/run", json={"backend": "claude"})
        assert resp.status == 400

    async def test_empty_prompt_returns_400(self, client: TestClient) -> None:
        resp = await client.post("/api/run", json={"prompt": "   "})
        assert resp.status == 400

    async def test_invalid_json_returns_400(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/run", data="not-json", headers={"Content-Type": "application/json"}
        )
        assert resp.status == 400

    async def test_unknown_backend_returns_400(self, client: TestClient) -> None:
        resp = await client.post("/api/run", json={"prompt": "hi", "backend": "gemini"})
        assert resp.status == 400

    async def test_explicit_backend_and_model_echoed(self, client: TestClient) -> None:
        resp = await client.post(
            "/api/run", json={"prompt": "hi", "backend": "codex", "model": "gpt-5.4"}
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["backend"] == "codex"
        assert data["model"] == "gpt-5.4"


class TestRunResult:
    async def test_run_completes_with_result(self, client: TestClient) -> None:
        resp = await client.post("/api/run", json={"prompt": "hello"})
        run_id = (await resp.json())["run_id"]
        data = await _poll_until_done(client, run_id)
        assert data["status"] == "done"
        assert data["result"] == "generated draft"

    async def test_default_backend_used_when_unspecified(
        self, client: TestClient, factory: _FakeFactory
    ) -> None:
        resp = await client.post("/api/run", json={"prompt": "hello"})
        run_id = (await resp.json())["run_id"]
        await _poll_until_done(client, run_id)
        assert factory.built[0]["backend"] == "claude"

    async def test_get_unknown_run_returns_404(self, client: TestClient) -> None:
        resp = await client.get("/api/run/deadbeef")
        assert resp.status == 404


class TestRunRepoRequired:
    async def test_503_when_run_repo_missing(self, notif_repo, bot) -> None:
        api = ApiServer(repo=notif_repo, bot=bot, host="127.0.0.1", port=0)
        server = TestServer(api.app)
        c = TestClient(server)
        await c.start_server()
        try:
            resp = await c.post("/api/run", json={"prompt": "hi"})
            assert resp.status == 503
        finally:
            await c.close()


class TestRunAuth:
    async def test_requires_bearer_when_secret_set(
        self, notif_repo, run_repo, factory, bot
    ) -> None:
        api = ApiServer(
            repo=notif_repo,
            bot=bot,
            run_repo=run_repo,
            backend_factory=factory,
            backend_settings=_FakeSettings(),
            api_secret="s3cret",
            host="127.0.0.1",
            port=0,
        )
        server = TestServer(api.app)
        c = TestClient(server)
        await c.start_server()
        try:
            resp = await c.post("/api/run", json={"prompt": "hi"})
            assert resp.status == 401
            resp = await c.post(
                "/api/run",
                json={"prompt": "hi"},
                headers={"Authorization": "Bearer s3cret"},
            )
            assert resp.status == 201
        finally:
            await c.close()
