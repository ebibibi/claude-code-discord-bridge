"""/remind slash command — schedules through ccdb's notification store.

This Cog used to carry its own SQLite wrapper, its own repository and its own
30-second send loop against a hardcoded ``data/bot.db``.  That made it the only
thing in the tree that delivered scheduled notifications, while the REST API
wrote to the deployment's ``notifications.db`` — so anything scheduled through
``POST /api/schedule`` was stored, listed, and never sent.

Delivery now belongs to ccdb's ``NotificationDispatchCog``, which reads the
same repository the API writes through.  What is left here is the part that is
genuinely EbiBot's: the ``/remind`` command.

Usage:
    CUSTOM_COGS_DIR=examples/ebibot/cogs ccdb start
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from claude_discord.database.notification_repo import NotificationRepository

logger = logging.getLogger(__name__)

_COLOR_REMINDER = 0x00BFFF
_COLOR_SUCCESS = 0x00FF00

_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")
_MAX_HOUR = 23
_MAX_MINUTE = 59


def _build_schedule_confirm_embed(message: str, scheduled_at: str) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Reminder scheduled!",
        description=f"**{scheduled_at}** — notification set.\n\n> {message}",
        color=_COLOR_SUCCESS,
        timestamp=datetime.now(),
    )
    embed.set_footer(text="EbiBot Reminder")
    return embed


class ReminderCog(commands.Cog):
    """The /remind slash command.  Delivery is ccdb's job, not this Cog's."""

    def __init__(self, bot: commands.Bot, repo: NotificationRepository) -> None:
        self.bot = bot
        self.repo = repo

    @app_commands.command(
        name="remind",
        description="Set a reminder at a specific time!",
    )
    @app_commands.describe(
        time="Time in HH:MM format",
        message="Reminder message",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        time: str,
        message: str,
    ) -> None:
        match = _TIME_PATTERN.match(time.strip())
        if not match:
            await interaction.response.send_message(
                "Please use HH:MM format (e.g. 14:30)",
                ephemeral=True,
            )
            return

        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= _MAX_HOUR and 0 <= minute <= _MAX_MINUTE):
            await interaction.response.send_message(
                "Time out of range! Use 00:00-23:59.",
                ephemeral=True,
            )
            return

        now = datetime.now()
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)

        # Local-time ISO without an offset — the form the dispatcher compares.
        await self.repo.create(
            message=message,
            scheduled_at=scheduled.strftime("%Y-%m-%dT%H:%M:%S"),
            color=_COLOR_REMINDER,
            source="slash_command",
            channel_id=interaction.channel_id,
        )

        embed = _build_schedule_confirm_embed(
            message=message,
            scheduled_at=scheduled.strftime("%m/%d %H:%M"),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot, runner: object, components: object) -> None:
    """Entry point for the custom Cog loader."""
    repo = getattr(components, "notification_repo", None)
    if repo is None:
        # No API server means no notification store and no dispatcher, so a
        # /remind that appeared to work would never fire.  Skip it loudly.
        logger.warning("ReminderCog skipped: no notification_repo (API server disabled?)")
        return
    await bot.add_cog(ReminderCog(bot, repo))
