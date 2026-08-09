"""Sending and editing activities in a Teams conversation.

The reply goes to the ``serviceUrl`` the conversation named — a regional Bot
Connector host, not a fixed endpoint. That is why :mod:`claude_teams.auth`
binds the token's ``serviceUrl`` claim to the body's: this module will
authenticate to whatever host it is handed, so the check that Microsoft named
the host has to happen before anything reaches here.

Editing is a first-class operation rather than an afterthought. The Teams
experience ccdb is aiming at is one session card that keeps up to date and one
answer that grows in place, which is a stream of edits to two activities — not
the column of new messages Discord's 2,000-character limit forces.
"""

from __future__ import annotations

import logging
from typing import Any

from .conversation import ConversationRef

__all__ = ["BotConnector"]

logger = logging.getLogger(__name__)


class BotConnector:
    """Posts and updates activities through the Bot Connector service."""

    def __init__(self, token_provider: Any, post_json: Any, put_json: Any | None = None) -> None:
        """
        Args:
            token_provider: object with ``async token() -> str``.
            post_json: ``async (url, payload: dict, headers: dict) -> Any``.
            put_json: the same for PUT. Optional so an existing caller that
                only ever sends keeps working; :meth:`update_activity` raises
                a clear error rather than silently doing nothing without it.
        """
        self._token_provider = token_provider
        self._post_json = post_json
        self._put_json = put_json

    async def send_text(self, ref: ConversationRef, text: str) -> str | None:
        """Post a plain-text message. Returns the new activity's id."""
        return await self.send_activity(ref, {"type": "message", "text": text})

    async def send_activity(self, ref: ConversationRef, body: dict[str, Any]) -> str | None:
        """Post an activity into *ref*'s conversation. Returns its id.

        The id is what makes the message editable later, so a caller that
        intends to update it must keep it. ``None`` means the service accepted
        the activity without naming it — possible, and the reason streaming
        checks for an id rather than assuming one.
        """
        response = await self._post_json(ref.activities_url, body, await self._headers())
        return _activity_id(response)

    async def update_activity(
        self, ref: ConversationRef, activity_id: str, body: dict[str, Any]
    ) -> None:
        """Replace an activity already in the conversation."""
        if self._put_json is None:
            raise RuntimeError("this connector was built without a PUT transport")
        await self._put_json(ref.activity_url(activity_id), body, await self._headers())

    async def _headers(self) -> dict[str, str]:
        token = await self._token_provider.token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _activity_id(response: Any) -> str | None:
    if isinstance(response, dict):
        value = response.get("id")
        if isinstance(value, str) and value:
            return value
    return None
