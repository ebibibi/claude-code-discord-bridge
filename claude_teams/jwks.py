"""Fetching and caching the Bot Connector's signing keys.

Two behaviours here are worth more than the HTTP call they wrap.

**Rotation is handled by refreshing on an unknown ``kid``, not by a timer.**
The connector rotates keys on its own schedule and does not announce it. A
purely time-based cache means every rotation produces a window where every
inbound request is rejected — the bot goes silent and comes back on its own,
which is the worst kind of incident to debug.

**Refreshes are rate-limited.** The trigger above is reachable by anyone: send
a token with a made-up ``kid`` and this process fetches a document. Without a
floor between refreshes that is an amplifier pointed at Microsoft, and a way
to stall the endpoint. Inside the floor, an unknown ``kid`` is simply rejected.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .auth import BOT_CONNECTOR_OPENID_METADATA, TokenError

__all__ = ["OpenIdKeyStore"]

#: Never refresh more often than this, in seconds, whatever asks.
DEFAULT_MIN_REFRESH_INTERVAL = 300.0

#: Refresh at least this often even if every key keeps resolving, so a removed
#: key stops being honoured within a bounded time.
DEFAULT_MAX_KEY_AGE = 24 * 3600.0


class OpenIdKeyStore:
    """Public keys from an OpenID metadata document, cached in memory."""

    def __init__(
        self,
        fetch_json: Any,
        *,
        metadata_url: str = BOT_CONNECTOR_OPENID_METADATA,
        min_refresh_interval: float = DEFAULT_MIN_REFRESH_INTERVAL,
        max_key_age: float = DEFAULT_MAX_KEY_AGE,
        now: Any = time.monotonic,
    ) -> None:
        """
        Args:
            fetch_json: ``async (url) -> dict``. Injected rather than built
                here so the store can be tested, and so a deployment can put
                its own retry or proxy policy in front of it.
        """
        self._fetch_json = fetch_json
        self._metadata_url = metadata_url
        self._min_refresh_interval = min_refresh_interval
        self._max_key_age = max_key_age
        self._now = now
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def key_for(self, kid: str) -> Any:
        """Return the public key for *kid*.

        Raises:
            TokenError: if the key is unknown and cannot be refreshed into
                view. Same type as every other inbound failure, so the endpoint
                keeps answering one thing.
        """
        key = self._keys.get(kid)
        if key is not None and not self._stale():
            return key

        async with self._lock:
            # Another waiter may have refreshed while this one queued.
            key = self._keys.get(kid)
            if key is not None and not self._stale():
                return key
            if self._may_refresh():
                await self._refresh()
            key = self._keys.get(kid)

        if key is None:
            raise TokenError(f"unknown signing key {kid!r}")
        return key

    def _stale(self) -> bool:
        return self._fetched_at is None or self._now() - self._fetched_at > self._max_key_age

    def _may_refresh(self) -> bool:
        return (
            self._fetched_at is None or self._now() - self._fetched_at >= self._min_refresh_interval
        )

    async def _refresh(self) -> None:
        metadata = await self._fetch_json(self._metadata_url)
        jwks_uri = metadata.get("jwks_uri") if isinstance(metadata, dict) else None
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise TokenError("OpenID metadata has no jwks_uri")
        document = await self._fetch_json(jwks_uri)
        self._keys = _parse_jwks(document)
        self._fetched_at = self._now()


def _parse_jwks(document: Any) -> dict[str, Any]:
    """Turn a JWKS document into ``kid -> public key``.

    A key that fails to parse is skipped rather than fatal: the connector
    publishes keys for algorithms this verifier does not accept, and one of
    them being unreadable must not take out every other key in the set.
    """
    from jwt import PyJWK

    keys: dict[str, Any] = {}
    entries = document.get("keys") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise TokenError("JWKS document has no keys")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid:
            continue
        try:
            keys[kid] = PyJWK(entry).key
        except Exception:  # noqa: BLE001 — one unusable key must not poison the set
            continue
    if not keys:
        raise TokenError("JWKS document contained no usable keys")
    return keys
