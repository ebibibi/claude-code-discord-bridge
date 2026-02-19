"""Session management Cog.

Provides slash commands for viewing and managing Claude Code sessions:
- /resume-info: Show CLI resume command for the current thread's session
- /sessions: List all known sessions (Discord and CLI originated)
- /sync-sessions: Import CLI sessions as Discord threads
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..database.repository import SessionRepository
from ..discord_ui.embeds import COLOR_INFO, COLOR_SUCCESS
from ..session_sync import scan_cli_sessions

if TYPE_CHECKING:
    from ..bot import ClaudeDiscordBot

logger = logging.getLogger(__name__)

_ORIGIN_ICON = {
    "discord": "\U0001f4ac",  # 💬
    "cli": "\U0001f5a5\ufe0f",  # 🖥️
}

_ORIGIN_CHOICES = [
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Discord", value="discord"),
    app_commands.Choice(name="CLI", value="cli"),
]


class SessionManageCog(commands.Cog):
    """Cog for session listing, resume info, and CLI sync commands."""

    def __init__(
        self,
        bot: ClaudeDiscordBot,
        repo: SessionRepository,
        cli_sessions_path: str | None = None,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.cli_sessions_path = cli_sessions_path

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
    @app_commands.describe(origin="Filter by session origin")
    @app_commands.choices(origin=_ORIGIN_CHOICES)
    async def sessions_list(
        self,
        interaction: discord.Interaction,
        origin: str | None = None,
    ) -> None:
        """List all sessions with origin, summary, and last activity."""
        # Convert "all" to None for the repository
        origin_filter = None if origin in (None, "all") else origin
        records = await self.repo.list_all(limit=25, origin=origin_filter)

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

    @app_commands.command(
        name="sync-sessions",
        description="Import CLI sessions from Claude Code as Discord threads",
    )
    async def sync_sessions(self, interaction: discord.Interaction) -> None:
        """Scan CLI session storage and create threads for unknown sessions."""
        if not self.cli_sessions_path:
            await interaction.response.send_message(
                "\u274c CLI sessions path is not configured. "
                "Set `cli_sessions_path` when initializing SessionManageCog.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Run CPU/IO-heavy scan in a thread to avoid blocking the event loop
        cli_sessions = await asyncio.to_thread(scan_cli_sessions, self.cli_sessions_path)
        raw_channel = self.bot.get_channel(self.bot.channel_id)

        imported = 0
        skipped = 0

        if not isinstance(raw_channel, discord.TextChannel):
            logger.warning("Channel %d is not a TextChannel", self.bot.channel_id)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="\U0001f504 Session Sync Complete",
                    description="Found **0** CLI session(s).\nChannel not available.",
                    color=COLOR_SUCCESS,
                )
            )
            return

        channel: discord.TextChannel = raw_channel

        for cli_session in cli_sessions:
            # Check if already tracked
            existing = await self.repo.get_by_session_id(cli_session.session_id)
            if existing:
                skipped += 1
                continue

            thread_name = (cli_session.summary or cli_session.session_id)[:100]
            thread = await channel.create_thread(
                name=f"\U0001f5a5 {thread_name}",
                type=discord.ChannelType.public_thread,
            )

            # Save to DB
            await self.repo.save(
                thread_id=thread.id,
                session_id=cli_session.session_id,
                working_dir=cli_session.working_dir,
                origin="cli",
                summary=cli_session.summary,
            )

            # Post info embed in the thread
            embed = discord.Embed(
                title="\U0001f5a5\ufe0f Imported CLI Session",
                description=(
                    f"This thread is linked to a Claude Code CLI session.\n"
                    f"Reply here to continue the conversation.\n\n"
                    f"```\nclaude --resume {cli_session.session_id}\n```"
                ),
                color=COLOR_INFO,
            )
            if cli_session.working_dir:
                embed.add_field(
                    name="Working Directory",
                    value=f"`{cli_session.working_dir}`",
                    inline=True,
                )
            if cli_session.timestamp:
                embed.add_field(name="Created", value=cli_session.timestamp[:10], inline=True)
            embed.set_footer(text=f"Session: {cli_session.session_id[:8]}...")

            await thread.send(embed=embed)
            imported += 1

        # Send result
        total_found = len(cli_sessions)
        embed = discord.Embed(
            title="\U0001f504 Session Sync Complete",
            description=(
                f"Found **{total_found}** CLI session(s).\n"
                f"\u2705 Imported: **{imported}**\n"
                f"\u23ed\ufe0f Already synced: **{skipped}**"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=embed)
