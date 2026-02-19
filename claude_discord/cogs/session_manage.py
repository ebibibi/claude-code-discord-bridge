"""Session management Cog.

Provides slash commands for viewing and managing Claude Code sessions:
- /resume-info: Show CLI resume command for the current thread's session
- /sessions: List all known sessions (Discord and CLI originated)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..database.repository import SessionRepository
from ..discord_ui.embeds import COLOR_INFO

if TYPE_CHECKING:
    from ..bot import ClaudeDiscordBot

logger = logging.getLogger(__name__)

_ORIGIN_ICON = {
    "discord": "\U0001f4ac",  # 💬
    "cli": "\U0001f5a5\ufe0f",  # 🖥️
}


class SessionManageCog(commands.Cog):
    """Cog for session listing and resume info commands."""

    def __init__(
        self,
        bot: ClaudeDiscordBot,
        repo: SessionRepository,
    ) -> None:
        self.bot = bot
        self.repo = repo

    @app_commands.command(
        name="resume-info",
        description="Show the CLI command to resume this thread's session",
    )
    async def resume_info(self, interaction: discord.Interaction) -> None:
        """Show the claude --resume command for the current thread."""
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This command can only be used in a Claude chat thread.",
                ephemeral=True,
            )
            return

        record = await self.repo.get(interaction.channel.id)
        if not record:
            await interaction.response.send_message(
                "No session found for this thread.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="\U0001f517 Resume from CLI",
            description=(
                f"```\nclaude --resume {record.session_id}\n```\n"
                f"Run this command in your terminal to continue this session."
            ),
            color=COLOR_INFO,
        )
        if record.working_dir:
            embed.add_field(name="Working Directory", value=f"`{record.working_dir}`", inline=True)
        if record.model:
            embed.add_field(name="Model", value=record.model, inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="sessions",
        description="List all known Claude Code sessions",
    )
    async def sessions_list(self, interaction: discord.Interaction) -> None:
        """List all sessions with origin, summary, and last activity."""
        records = await self.repo.list_all(limit=25)

        if not records:
            embed = discord.Embed(
                title="\U0001f4cb Sessions",
                description="No sessions found.",
                color=COLOR_INFO,
            )
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            title=f"\U0001f4cb Sessions ({len(records)})",
            color=COLOR_INFO,
        )

        for record in records:
            icon = _ORIGIN_ICON.get(record.origin, "\u2753")
            summary = record.summary or "(no summary)"
            session_short = record.session_id[:8]

            name = f"{icon} {summary[:50]}"
            value = f"`{session_short}...` | {record.last_used_at}"
            if record.working_dir:
                # Show just the last directory component
                dir_short = record.working_dir.rsplit("/", 1)[-1]
                value += f" | `{dir_short}`"

            embed.add_field(name=name, value=value, inline=False)

        await interaction.response.send_message(embed=embed)
