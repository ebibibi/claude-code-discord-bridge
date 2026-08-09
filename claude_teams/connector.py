"""Sending an activity back to Teams.

The reply goes to the ``serviceUrl`` the inbound activity named — a regional
Bot Connector host, not a fixed endpoint. That is why
:mod:`claude_teams.auth` binds the token's ``serviceUrl`` claim to the body's:
this module will authenticate to whatever host it is handed, so the check that
the host was named by Microsoft has to happen before it gets here.
"""

from __future__ import annotations

from typing import Any

from .activity import InboundActivity

__all__ = ["BotConnector"]


class BotConnector:
    """Posts activities to the Bot Connector service."""

    def __init__(self, token_provider: Any, post_json: Any) -> None:
        """
        Args:
            token_provider: object with ``async token() -> str``.
            post_json: ``async (url, payload: dict, headers: dict) -> Any``.
                Injected for the same reason as elsewhere in this package: the
                HTTP client is a deployment concern, not a protocol one.
        """
        self._token_provider = token_provider
        self._post_json = post_json

    async def send_text(self, activity: InboundActivity, text: str) -> Any:
        """Reply to *activity* with a plain-text message."""
        return await self.send_activity(
            activity,
            {
                "type": "message",
                "text": text,
                # Threads the reply under the message being answered. Without
                # it a channel reply starts a new conversation and the session
                # visibly detaches from what the user said.
                "replyToId": activity.id or None,
            },
        )

    async def send_activity(self, activity: InboundActivity, body: dict[str, Any]) -> Any:
        """Post an arbitrary activity body into *activity*'s conversation."""
        base = activity.service_url.rstrip("/")
        url = f"{base}/v3/conversations/{activity.conversation_id}/activities"
        if activity.id:
            url = f"{url}/{activity.id}"
        token = await self._token_provider.token()
        return await self._post_json(
            url,
            body,
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
