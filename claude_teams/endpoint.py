"""The HTTPS endpoint Teams delivers activities to.

This is the first part of ccdb that is reachable from the open internet, and
what sits behind it starts coding-agent sessions with a shell. So the shape of
this handler is driven less by what Teams sends than by what an unauthenticated
caller must not be able to cause:

* **Nothing before the token check.** The body is not parsed, and no work is
  scheduled, until :mod:`claude_teams.auth` has approved the request. The one
  exception is reading ``serviceUrl``, which the verifier itself needs — done
  under a size limit, and used for nothing else if verification fails.
* **A size limit that applies to strangers.** Reading an arbitrary body into
  memory to discover it was junk is the cheapest denial of service available.
* **4xx and 5xx are not interchangeable.** Teams redelivers on 5xx. A downstream
  failure that answers 500 turns one user message into a retry loop that
  processes it again and again, so failures after acceptance are logged and
  answered 200.
* **An invoke is answered in the response body.** A card press does not arrive
  like a message: Teams reads the HTTP body as the answer, so a bare
  ``{"status": "ok"}`` shows the user an error even though the press worked.
  Messages keep the plain body; only invokes carry an ``InvokeResponse``.

Why aiohttp and not the framework the design sketch named
--------------------------------------------------------
ccdb already runs an aiohttp server in this process (``ext/api_server.py``).
Adding a second HTTP framework to serve one route would mean two servers, two
sets of middleware and two lifecycles inside one bot, and buy nothing: what
this handler needs is a route and a request body. The deviation is deliberate
and its cost is one import, not an architecture.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from aiohttp import web

from .activity import INVOKE, InboundActivity, parse_activity
from .auth import TokenError
from .config import DEFAULT_ENDPOINT_PATH
from .conversation import ConversationRef
from .interactions import InteractionRegistry

__all__ = ["TeamsEndpoint"]

logger = logging.getLogger(__name__)

#: Largest inbound body accepted. Teams activities are small; the cap exists
#: for everyone who is not Teams.
DEFAULT_MAX_BODY_BYTES = 512 * 1024

#: The invoke Teams sends when a Universal Action (``Action.Execute``) is
#: pressed.
ADAPTIVE_CARD_ACTION = "adaptiveCard/action"

_INVOKE_MESSAGE_TYPE = "application/vnd.microsoft.activity.message"

#: What the user sees when their press could not be applied. Deliberately one
#: sentence for every reason — "wrong conversation" and "expired" are both free
#: information to whoever is probing.
_REFUSED_TEXT = "This prompt is no longer active."

MessageHandler = Callable[[InboundActivity], Awaitable[None]]


class Verifier(Protocol):
    async def verify(
        self, authorization: str | None, *, service_url: str | None
    ) -> dict[str, Any]: ...


class Connector(Protocol):
    async def send_text(self, ref: ConversationRef, text: str) -> Any: ...


class TeamsEndpoint:
    """Receives Bot Framework activities and dispatches them."""

    def __init__(
        self,
        app_id: str,
        verifier: Verifier,
        connector: Connector,
        *,
        path: str = DEFAULT_ENDPOINT_PATH,
        on_message: MessageHandler | None = None,
        interactions: InteractionRegistry | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        """
        Args:
            on_message: What to do with an inbound message. Defaults to an
                echo, which is what makes this skeleton provable end to end
                before a surface exists. The session frontend replaces it.
            interactions: Where prompts wait to be answered. One registry is
                shared with every surface in the deployment, so a press has a
                single place to be routed to.
        """
        self.app_id = app_id
        self.path = path
        self._verifier = verifier
        self._connector = connector
        self._on_message = on_message or self._echo
        self._interactions = interactions or InteractionRegistry()
        self._max_body_bytes = max_body_bytes

    @property
    def interactions(self) -> InteractionRegistry:
        return self._interactions

    def add_routes(self, app: web.Application) -> None:
        """Register this endpoint on an existing aiohttp application."""
        app.router.add_post(self.path, self.handle)

    async def handle(self, request: web.Request) -> web.Response:
        try:
            payload = await self._read_body(request)
        except _BodyTooLargeError:
            return web.json_response({"error": "payload too large"}, status=413)
        except _BadBodyError:
            return web.json_response({"error": "invalid request"}, status=400)

        service_url = payload.get("serviceUrl") if isinstance(payload, dict) else None
        try:
            await self._verifier.verify(
                request.headers.get("Authorization"),
                service_url=service_url if isinstance(service_url, str) else None,
            )
        except TokenError as exc:
            # The reason is worth having locally and worth withholding from the
            # caller, who may be probing.
            logger.warning("Rejected inbound Teams activity: %s", exc)
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            activity = parse_activity(payload)
        except ValueError as exc:
            logger.warning("Malformed Teams activity: %s", exc)
            return web.json_response({"error": "invalid activity"}, status=400)

        if activity.type == INVOKE:
            return self._handle_invoke(activity)

        if activity.is_message and not activity.is_from(self.app_id):
            try:
                await self._on_message(activity)
            except Exception:
                # Accepted and mishandled. Answering 5xx here would have Teams
                # redeliver it, so the user's message would be processed again
                # on every retry.
                logger.exception("Teams message handler failed")

        return web.json_response({"status": "ok"})

    def _handle_invoke(self, activity: InboundActivity) -> web.Response:
        """Answer a card press inline.

        Every outcome is HTTP 200 with an ``InvokeResponse`` body. A failure
        status here reaches the user as an error dialog, and "you pressed an
        expired button" is not an error they made.
        """
        if activity.raw.get("name") != ADAPTIVE_CARD_ACTION:
            # Teams sends invokes ccdb does not implement, and more over time.
            # Answering them with a failure surfaces as a broken bot.
            return _invoke_message("")

        value = activity.raw.get("value")
        action = value.get("action") if isinstance(value, dict) else None
        data = action.get("data") if isinstance(action, dict) else None

        if self._interactions.resolve(activity.conversation_id, data):
            return _invoke_message("Recorded.")
        logger.info("A Teams card action did not match a live prompt")
        return _invoke_message(_REFUSED_TEXT)

    async def _read_body(self, request: web.Request) -> Any:
        declared = request.content_length
        if declared is not None and declared > self._max_body_bytes:
            raise _BodyTooLargeError
        raw = await request.content.read(self._max_body_bytes + 1)
        if len(raw) > self._max_body_bytes:
            raise _BodyTooLargeError
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _BadBodyError from exc

    async def _echo(self, activity: InboundActivity) -> None:
        await self._connector.send_text(activity.ref, f"echo: {activity.text}")


def _invoke_message(text: str) -> web.Response:
    return web.json_response({"statusCode": 200, "type": _INVOKE_MESSAGE_TYPE, "value": text})


class _BodyTooLargeError(Exception):
    pass


class _BadBodyError(Exception):
    pass
