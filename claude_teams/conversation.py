"""Where a reply goes.

Teams does not have one API host. Each activity names the regional Bot
Connector that owns its conversation, and a reply has to go back to that one —
so "the address of a conversation" is a pair, not an id.

Splitting it out of :class:`~claude_teams.activity.InboundActivity` matters
because most of what ccdb does is *not* a reply. A scheduled task, a webhook,
and the REST API all want to post into a conversation nobody just spoke in, and
they have no inbound activity to hold.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ConversationRef"]


@dataclass(frozen=True)
class ConversationRef:
    """The Bot Connector host and conversation a message belongs to."""

    service_url: str
    conversation_id: str
    #: The activity a reply should thread under. Optional because a scheduled
    #: post is not a reply to anything.
    reply_to_id: str | None = None

    def __post_init__(self) -> None:
        if not self.service_url:
            raise ValueError("service_url must not be empty")
        if not self.conversation_id:
            raise ValueError("conversation_id must not be empty")

    @property
    def activities_url(self) -> str:
        """Where to POST a new activity into this conversation."""
        base = f"{self.service_url.rstrip('/')}/v3/conversations/{self.conversation_id}/activities"
        return f"{base}/{self.reply_to_id}" if self.reply_to_id else base

    def activity_url(self, activity_id: str) -> str:
        """Where to PUT an update to an activity already in this conversation."""
        if not activity_id:
            raise ValueError("activity_id must not be empty")
        return (
            f"{self.service_url.rstrip('/')}/v3/conversations/"
            f"{self.conversation_id}/activities/{activity_id}"
        )

    def without_reply(self) -> ConversationRef:
        """The same conversation, addressed as a fresh post rather than a reply."""
        return ConversationRef(self.service_url, self.conversation_id)
