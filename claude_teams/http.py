"""The aiohttp glue, kept in one file so the rest of the package has none.

Every module that talks to a network takes its transport as a callable. That is
not indirection for its own sake: it is what lets the token cache, the key
rotation policy and the endpoint's refusal rules be tested exactly, with no
HTTP server and no sleeping. This file is the one place that knows about
aiohttp, and it is deliberately thin enough to read in full.

Error bodies are never included in raised messages. The token endpoint in
particular echoes request parameters back in ``error_description``, and the
request carries the client secret.
"""

from __future__ import annotations

from typing import Any

from aiohttp import ClientSession, ClientTimeout

from .auth import InboundTokenVerifier
from .config import TeamsConfig
from .connector import BotConnector
from .endpoint import MessageHandler, TeamsEndpoint
from .jwks import OpenIdKeyStore
from .token import OutboundTokenProvider

__all__ = ["build_endpoint", "form_poster", "json_fetcher", "json_poster"]

#: Applies to every outbound call this package makes. aiohttp stopped accepting
#: a bare number here, and a request with no timeout at all is how a hung
#: connector call becomes a session that never finishes streaming.
DEFAULT_TIMEOUT = ClientTimeout(total=30)


def json_fetcher(session: ClientSession) -> Any:
    async def fetch(url: str) -> Any:
        async with session.get(url, timeout=DEFAULT_TIMEOUT) as response:
            if response.status != 200:
                raise RuntimeError(f"GET {url} returned {response.status}")
            return await response.json()

    return fetch


def form_poster(session: ClientSession) -> Any:
    async def post(url: str, data: dict[str, str]) -> Any:
        async with session.post(url, data=data, timeout=DEFAULT_TIMEOUT) as response:
            if response.status != 200:
                # No body: this is the token endpoint, and its error text can
                # contain the secret that was just sent to it.
                raise RuntimeError(f"token request failed with {response.status}")
            return await response.json()

    return post


def json_poster(session: ClientSession) -> Any:
    async def post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        async with session.post(
            url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT
        ) as response:
            if response.status >= 400:
                raise RuntimeError(f"POST {url} returned {response.status}")
            if response.content_type == "application/json":
                return await response.json()
            return None

    return post


def build_endpoint(
    config: TeamsConfig,
    session: ClientSession,
    *,
    on_message: MessageHandler | None = None,
) -> TeamsEndpoint:
    """Assemble a ready-to-mount endpoint from configuration.

    Raises:
        ValueError: if the config cannot authenticate outbound calls. A bot
            that can receive but not reply is worse than one that refuses to
            start: it looks installed and answers nothing.
    """
    if not config.can_send_outbound or config.app_password is None:
        raise ValueError("CCDB_TEAMS_APP_PASSWORD is required to reply to Teams")

    verifier = InboundTokenVerifier(
        app_id=config.app_id,
        key_store=OpenIdKeyStore(json_fetcher(session)),
    )
    connector = BotConnector(
        OutboundTokenProvider(
            config.tenant_id,
            config.app_id,
            config.app_password,
            form_poster(session),
        ),
        json_poster(session),
    )
    return TeamsEndpoint(
        app_id=config.app_id,
        verifier=verifier,
        connector=connector,
        path=config.endpoint_path,
        on_message=on_message,
    )
