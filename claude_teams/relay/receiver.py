"""The part that faces the internet, and holds nothing worth stealing.

It does exactly three things: verify the inbound token, put the activity on a
queue, and answer. It cannot reply to Teams — it has no client secret — and it
cannot reach the session host, which has no listening port. What an attacker
gets by owning it is the traffic that flows through it from that moment on.

Why it verifies rather than forwarding blindly
----------------------------------------------
Passing unverified bodies to the queue would make the queue the trust boundary
and the session host the thing that has to check. That is worse in both
directions: the queue would carry attacker-controlled junk, and the host would
need the Bot Connector's keys to judge it. Verifying here means the queue only
ever contains activities Microsoft signed, and the host can spend its trust on
one thing — that this process did its job — which the envelope records.

The invoke compromise
---------------------
Teams reads the HTTP response body as the answer to a card press, within
seconds. This process cannot know whether the prompt is still live, so it
acknowledges every well-formed press and enqueues it. The user sees the press
succeed even when the prompt has expired; the *effect* is still refused, on the
host, by the registry that owns the prompt. Precision of feedback, traded for
keeping the host off the internet.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from aiohttp import web

from ..activity import INVOKE
from ..auth import TokenError
from ..config import DEFAULT_ENDPOINT_PATH
from .envelope import Envelope, EnvelopeTooLargeError

logger = logging.getLogger(__name__)

__all__ = ["RelayReceiver"]

DEFAULT_MAX_BODY_BYTES = 512 * 1024

_INVOKE_MESSAGE_TYPE = "application/vnd.microsoft.activity.message"

#: What a card press gets back. Deliberately says nothing about whether the
#: prompt was live: this process does not know, and inventing an answer would
#: be worse than a neutral one.
_INVOKE_ACK = ""


class Verifier(Protocol):
    async def verify(
        self, authorization: str | None, *, service_url: str | None
    ) -> dict[str, Any]: ...


class Queue(Protocol):
    async def push(self, text: str) -> None: ...


class RelayReceiver:
    """An HTTPS endpoint that verifies, enqueues, and forgets."""

    def __init__(
        self,
        verifier: Verifier,
        queue: Queue,
        *,
        path: str = DEFAULT_ENDPOINT_PATH,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        now: Any = None,
    ) -> None:
        self._verifier = verifier
        self._queue = queue
        self.path = path
        self._max_body_bytes = max_body_bytes
        self._now = now

    def add_routes(self, app: web.Application) -> None:
        app.router.add_post(self.path, self.handle)
        app.router.add_get("/healthz", self._healthz)

    async def handle(self, request: web.Request) -> web.Response:
        try:
            payload = await self._read_body(request)
        except _TooLargeError:
            return web.json_response({"error": "payload too large"}, status=413)
        except _BadBodyError:
            return web.json_response({"error": "invalid request"}, status=400)

        body_service_url = payload.get("serviceUrl") if isinstance(payload, dict) else None
        try:
            claims = await self._verifier.verify(
                request.headers.get("Authorization"),
                service_url=body_service_url if isinstance(body_service_url, str) else None,
            )
        except TokenError as exc:
            logger.warning("Rejected inbound Teams activity: %s", exc)
            return web.json_response({"error": "unauthorized"}, status=401)

        # Address from the *token's* claim, never the body's. Same rule the
        # inline endpoint enforces; moving machines must not lose it.
        service_url = _service_url_from(claims) or body_service_url
        if not isinstance(service_url, str) or not service_url:
            logger.error("Verified token carried no serviceurl — refusing to enqueue")
            return web.json_response({"error": "unauthorized"}, status=401)

        is_invoke = isinstance(payload, dict) and payload.get("type") == INVOKE
        try:
            envelope = (
                Envelope.wrap(payload, service_url, now=self._now)
                if self._now
                else Envelope.wrap(payload, service_url)
            )
            await self._queue.push(envelope.encode())
        except EnvelopeTooLargeError as exc:
            # Loud and specific: the message is gone either way, and "too big"
            # is something an operator can act on.
            logger.error("Dropped an oversized Teams activity: %s", exc)
            return self._answer(is_invoke, status=200)
        except Exception:
            # The queue is down. 5xx makes Teams redeliver, which is exactly
            # what should happen — unlike a failure *after* the work is safely
            # stored, this one has lost the message.
            logger.exception("Failed to enqueue a Teams activity")
            return web.json_response({"error": "unavailable"}, status=503)

        return self._answer(is_invoke, status=200)

    def _answer(self, is_invoke: bool, *, status: int) -> web.Response:
        if is_invoke:
            return web.json_response(
                {"statusCode": 200, "type": _INVOKE_MESSAGE_TYPE, "value": _INVOKE_ACK},
                status=status,
            )
        return web.json_response({"status": "ok"}, status=status)

    async def _healthz(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _read_body(self, request: web.Request) -> Any:
        declared = request.content_length
        if declared is not None and declared > self._max_body_bytes:
            raise _TooLargeError
        raw = await request.content.read(self._max_body_bytes + 1)
        if len(raw) > self._max_body_bytes:
            raise _TooLargeError
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _BadBodyError from exc


def _service_url_from(claims: dict[str, Any]) -> str | None:
    for name in ("serviceurl", "serviceUrl"):
        value = claims.get(name)
        if isinstance(value, str) and value:
            return value
    return None


class _TooLargeError(Exception):
    pass


class _BadBodyError(Exception):
    pass
