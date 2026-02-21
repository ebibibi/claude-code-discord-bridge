"""CoordinationService — posts session lifecycle events to the coordination channel.

The coordination channel is a shared Discord channel where Claude Code sessions
broadcast what they are doing. This enables multiple concurrent sessions to be
aware of each other and avoid accidental conflicts.

Bot side (this module):
  - Auto-posts session start / end events
  - Feature is a no-op when COORDINATION_CHANNEL_ID is not configured

Claude side (see ~/.claude/skills/coordination-channel/):
  - Uses coord_post.py / coord_read.py scripts to post / read at will
"""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger(__name__)


class CoordinationService:
    """Posts lifecycle events to a shared coordination channel.

    All methods are safe to call when no coordination channel is configured —
    they become no-ops, so consumers never need to guard against None.
    """

    def __init__(self, bot: discord.Client, channel_id: int | None) -> None:
        self._bot = bot
        self._channel_id = channel_id

    @property
    def enabled(self) -> bool:
        return self._channel_id is not None

    def _get_channel(self) -> discord.TextChannel | None:
        if self._channel_id is None:
            return None
        channel = self._bot.get_channel(self._channel_id)
        if channel is None:
            logger.warning("Coordination channel %d not found in bot cache", self._channel_id)
        return channel  # type: ignore[return-value]

    async def post_session_end(self, thread: discord.Thread) -> None:
        """Post a session-ended notice to the coordination channel."""
        channel = self._get_channel()
        if channel is None:
            return
        content = f"✅ **{thread.name}** セッション終了"
        await self._safe_send(channel, content)

    async def _safe_send(self, channel: discord.TextChannel, content: str) -> None:
        """Send a message, swallowing HTTP errors so lifecycle events never crash."""
        try:
            await channel.send(content)
        except discord.HTTPException:
            logger.warning(
                "Failed to post to coordination channel %d", self._channel_id, exc_info=True
            )
