"""``python -m claude_teams serve`` — run the endpoint and nothing else.

This is the smallest thing that can prove a Teams message reaches this process
and gets answered: an aiohttp server with one route, the echo handler, and no
session machinery anywhere near it.

That is the point, not a limitation. Bringing a Teams app up for the first time
means checking a chain — Entra app, Azure Bot registration, messaging endpoint,
manifest, resource-specific consent, token validation — where any broken link
produces the same symptom: silence. A process that *only* echoes turns that
into one question with one answer, and while it is running, the thing reachable
from the internet cannot start a session even if it is compromised.

Wiring Teams into a deployment that actually runs sessions is a different
entry point, deliberately.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys

from aiohttp import ClientSession, web

from .config import TeamsConfig
from .http import build_endpoint

logger = logging.getLogger(__name__)

__all__ = ["serve"]

#: Loopback by default. Anything reaching this process should have come
#: through a tunnel or a proxy that terminated TLS and can be pointed
#: somewhere else; binding to every interface by accident is how a first
#: experiment turns into an open port.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3978


async def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the echo endpoint until interrupted."""
    config = TeamsConfig.from_env(os.environ)
    async with ClientSession() as session:
        endpoint = build_endpoint(config, session)
        app = web.Application()
        endpoint.add_routes(app)
        app.router.add_get("/healthz", _healthz)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        logger.info("Teams echo endpoint listening on http://%s:%s%s", host, port, endpoint.path)
        logger.info("Bot app id %s — this process echoes and starts no sessions", config.app_id)
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


async def _healthz(_request: web.Request) -> web.Response:
    """Unauthenticated liveness check.

    Says nothing about the deployment — no app id, no tenant, no version.
    A health endpoint is the most-scanned URL on any host, and one that
    identifies what it is fronting is free reconnaissance.
    """
    return web.json_response({"status": "ok"})


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m claude_teams serve")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(serve(args.host, args.port))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
