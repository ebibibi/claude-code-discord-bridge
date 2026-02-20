"""Discord Bot class."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .concurrency import SessionRegistry
from .coordination.service import CoordinationService

if TYPE_CHECKING:
    from .discord_ui.thread_dashboard import ThreadStatusDashboard

logger = logging.getLogger(__name__)


class ClaudeDiscordBot(commands.Bot):
    """Discord bot that bridges messages to Claude Code CLI."""

    def __init__(
        self,
        channel_id: int,
        owner_id: int | None = None,
        coordination_channel_id: int | None = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        super().__init__(
            command_prefix="!",  # Not used, but required
            intents=intents,
        )
        self.channel_id = channel_id
        self.owner_id = owner_id
        self.session_registry = SessionRegistry()
        # Populated after on_ready when the channel is resolved
        self.thread_dashboard: ThreadStatusDashboard | None = None
        # Coordination channel for multi-session awareness (optional)
        self.coordination = CoordinationService(self, coordination_channel_id)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        logger.info("Watching channel ID: %d", self.channel_id)

        # Initialise the thread-status dashboard once we have a live channel object
        channel = self.get_channel(self.channel_id)
        if isinstance(channel, discord.TextChannel):
            from .discord_ui.thread_dashboard import ThreadStatusDashboard

            self.thread_dashboard = ThreadStatusDashboard(
                channel=channel,
                owner_id=self.owner_id,
            )
            await self.thread_dashboard.initialize()
            logger.info("Thread status dashboard initialised in channel %d", self.channel_id)
        else:
            logger.warning(
                "Could not resolve channel %d to a TextChannel; dashboard disabled",
                self.channel_id,
            )

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception:
            logger.exception("Failed to sync slash commands")
