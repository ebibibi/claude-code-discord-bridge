"""The credential this process presents when it talks back to Teams.

A client-credentials token, cached until shortly before it expires. The cache
is the point: the token is valid for an hour, and fetching one per outbound
message would add a round trip to every line of streamed output and hit the
identity platform's own throttling long before Teams' 1,800-per-hour budget
became the limit.

Refreshing *early* rather than on failure matters for the same reason. A token
that expires mid-stream produces a 401 on one message in the middle of an
answer, which reads to the user as the bot losing its place.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

__all__ = ["OutboundTokenProvider"]

#: Scope for the Bot Connector service.
BOT_CONNECTOR_SCOPE = "https://api.botframework.com/.default"

#: Renew this many seconds before the token actually expires.
DEFAULT_REFRESH_MARGIN = 300.0


class OutboundTokenProvider:
    """Fetches and caches an app-only token for the Bot Connector."""

    def __init__(
        self,
        tenant_id: str,
        app_id: str,
        app_password: str,
        post_form: Any,
        *,
        scope: str = BOT_CONNECTOR_SCOPE,
        refresh_margin: float = DEFAULT_REFRESH_MARGIN,
        now: Any = time.monotonic,
    ) -> None:
        """
        Args:
            post_form: ``async (url, data: dict) -> dict`` returning the parsed
                token response. Injected so this module needs no HTTP client
                and can be tested without one.
        """
        self._tenant_id = tenant_id
        self._app_id = app_id
        self._app_password = app_password
        self._post_form = post_form
        self._scope = scope
        self._refresh_margin = refresh_margin
        self._now = now
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"

    async def token(self) -> str:
        """Return a valid access token, fetching one if the cache is cold."""
        if self._token is not None and self._now() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token is not None and self._now() < self._expires_at:
                return self._token
            response = await self._post_form(
                self.token_url,
                {
                    "grant_type": "client_credentials",
                    "client_id": self._app_id,
                    "client_secret": self._app_password,
                    "scope": self._scope,
                },
            )
            self._token = _access_token(response)
            self._expires_at = self._now() + _lifetime(response) - self._refresh_margin
            return self._token

    def invalidate(self) -> None:
        """Drop the cached token so the next call fetches a fresh one.

        For the case the margin cannot cover: the service rejected a token this
        process still believes in, usually because the secret was rotated.
        """
        self._token = None
        self._expires_at = 0.0


def _access_token(response: Any) -> str:
    token = response.get("access_token") if isinstance(response, dict) else None
    if not isinstance(token, str) or not token:
        # Never include the response body: it can carry the request's own
        # client_secret back in an error description.
        raise RuntimeError("token endpoint returned no access_token")
    return token


def _lifetime(response: dict[str, Any]) -> float:
    expires_in = response.get("expires_in")
    if isinstance(expires_in, int | float) and expires_in > 0:
        return float(expires_in)
    # A response without a lifetime is not worth guessing generously about.
    return 600.0
