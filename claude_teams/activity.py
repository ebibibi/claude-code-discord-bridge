"""The inbound Activity, reduced to what ccdb actually addresses.

Teams posts a large JSON document per event. Parsing it into a narrow value
object here means the rest of the package never reaches into raw dictionaries,
and — more usefully — that a missing field fails in one place with a name
attached instead of surfacing as ``None`` three layers later.

``conversation.id`` is the field everything hinges on. It is the string that
:func:`claude_code_core.frontend.derive_thread_key` turns into a ThreadKey, and
in a channel it already encodes the reply chain (``...;messageid=...``), which
is why a Teams "thread" can map onto ccdb's Thread=Session rule at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claude_code_core.frontend import Mention

from .conversation import ConversationRef
from .mentions import mentions_in, strip_mention_markup, was_mentioned

__all__ = ["InboundActivity", "parse_activity"]

MESSAGE = "message"
INVOKE = "invoke"
CONVERSATION_UPDATE = "conversationUpdate"


@dataclass(frozen=True)
class InboundActivity:
    """One event from Teams."""

    type: str
    id: str
    service_url: str
    conversation_id: str
    from_id: str
    from_name: str
    recipient_id: str
    text: str
    conversation_type: str | None
    tenant_id: str | None
    channel_id: str | None
    team_id: str | None
    locale: str | None
    raw: dict[str, Any]

    @property
    def ref(self) -> ConversationRef:
        """Where a reply to this activity goes, threaded under it."""
        return ConversationRef(
            service_url=self.service_url,
            conversation_id=self.conversation_id,
            reply_to_id=self.id or None,
            conversation_type=self.conversation_type,
        )

    @property
    def is_message(self) -> bool:
        return self.type == MESSAGE

    def mentions_bot(self, app_id: str) -> bool:
        """Whether this message @mentioned *app_id*, by id rather than name."""
        return was_mentioned(self.raw, app_id)

    def mentions(self, *, exclude: str = "") -> tuple[Mention, ...]:
        """Everyone mentioned, optionally minus one id — normally the bot's."""
        return mentions_in(self.raw, exclude=exclude)

    @property
    def clean_text(self) -> str:
        """The text with mention markup removed — what the model should see.

        ``text`` is what Teams delivered, tags and all. Handing that to a
        session makes it learn to strip ``<at>…</at>`` itself, and puts a tag
        in front of any command the user typed.
        """
        return strip_mention_markup(self.text)

    def is_from(self, app_id: str) -> bool:
        """Whether this activity is the bot hearing itself.

        Teams echoes a bot's own channel posts back to it. Without this check
        the first reply becomes the next request and the conversation runs away
        as fast as the rate limiter allows.
        """
        return bool(app_id) and self.from_id == app_id


def parse_activity(payload: Any) -> InboundActivity:
    """Parse an inbound activity body.

    Raises:
        ValueError: naming the field, if the body is not an activity or is
            missing something without which no reply can be addressed.
    """
    if not isinstance(payload, dict):
        raise ValueError("activity body must be a JSON object")

    def text_field(*path: str, required: bool = False) -> str:
        node: Any = payload
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, str) and node:
            return node
        if required:
            raise ValueError(f"activity is missing {'.'.join(path)}")
        return ""

    channel_data = payload.get("channelData")
    channel_data = channel_data if isinstance(channel_data, dict) else {}
    conversation = payload.get("conversation")
    conversation = conversation if isinstance(conversation, dict) else {}

    return InboundActivity(
        type=text_field("type", required=True),
        id=text_field("id"),
        service_url=text_field("serviceUrl", required=True),
        conversation_id=text_field("conversation", "id", required=True),
        from_id=text_field("from", "id"),
        from_name=text_field("from", "name"),
        recipient_id=text_field("recipient", "id"),
        text=_string(payload, "text") or "",
        conversation_type=_nested(conversation, "conversationType"),
        tenant_id=_nested(channel_data, "tenant", "id"),
        channel_id=_nested(channel_data, "channel", "id"),
        team_id=_nested(channel_data, "team", "id"),
        locale=_string(payload, "locale"),
        raw=payload,
    )


def _string(node: dict[str, Any], key: str) -> str | None:
    value = node.get(key)
    return value if isinstance(value, str) and value else None


def _nested(node: dict[str, Any], *path: str) -> str | None:
    current: Any = node
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return current if isinstance(current, str) and current else None
