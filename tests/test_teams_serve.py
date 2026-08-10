"""The echo runner: what it exposes, and what it must not."""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from claude_teams.serve import DEFAULT_HOST, _healthz


class TestDefaults:
    def test_it_binds_to_loopback_by_default(self) -> None:
        # Binding every interface by accident is how a first experiment turns
        # into an open port. Whatever fronts this should be replaceable.
        assert DEFAULT_HOST == "127.0.0.1"


class TestHealth:
    async def test_the_health_check_identifies_nothing(self) -> None:
        # The most-scanned URL on any host. One that names the app id or the
        # tenant is free reconnaissance.
        app = web.Application()
        app.router.add_get("/healthz", _healthz)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/healthz")
            assert response.status == 200
            assert await response.json() == {"status": "ok"}
        finally:
            await client.close()
