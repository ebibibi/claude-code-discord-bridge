"""Discord Bot class."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .concurrency import SessionRegistry

logger = logging.getLogger(__name__)


class ClaudeDiscordBot(commands.Bot):
    """Discord bot that bridges messages to Claude Code CLI."""

    def __init__(self, channel_id: int) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        super().__init__(
            command_prefix="!",  # Not used, but required
            intents=intents,
        )
        self.channel_id = channel_id
        self.session_registry = SessionRegistry()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        logger.info("Watching channel ID: %d", self.channel_id)

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception:
            logger.exception("Failed to sync slash commands")
