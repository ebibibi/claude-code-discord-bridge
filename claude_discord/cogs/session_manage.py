"""Session management Cog.

Provides slash commands for viewing and managing Claude Code sessions:
- /resume-info: Show CLI resume command for the current thread's session
- /sessions: List all known sessions (Discord and CLI originated)
- /sync-sessions: Import CLI sessions as Discord threads
- /sync-settings: Configure session sync preferences (thread style)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..database.repository import SessionRepository
from ..database.settings_repo import SettingsRepository
from ..discord_ui.embeds import COLOR_INFO, COLOR_SUCCESS, COLOR_TOOL
from ..session_sync import CliSession, extract_recent_messages, scan_cli_sessions
from ..worktree import WorktreeManager

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

SETTING_SYNC_THREAD_STYLE = "sync_thread_style"
THREAD_STYLE_CHANNEL = "channel"
THREAD_STYLE_MESSAGE = "message"
_VALID_THREAD_STYLES = {THREAD_STYLE_CHANNEL, THREAD_STYLE_MESSAGE}

_STYLE_CHOICES = [
    app_commands.Choice(name="Channel threads (hidden in panel)", value=THREAD_STYLE_CHANNEL),
    app_commands.Choice(name="Message threads (visible in channel)", value=THREAD_STYLE_MESSAGE),
]

SETTING_SYNC_SINCE_HOURS = "sync_since_hours"
_DEFAULT_SINCE_HOURS = 24
SETTING_SYNC_MIN_RESULTS = "sync_min_results"
_DEFAULT_MIN_RESULTS = 10

# Model management
SETTING_CLAUDE_MODEL = "claude_model"
_VALID_MODELS = {"haiku", "sonnet", "opus"}
_MODEL_CHOICES = [
    app_commands.Choice(name="Haiku 4.5 (fast, cost-effective)", value="haiku"),
    app_commands.Choice(name="Sonnet 4.6 (balanced, default)", value="sonnet"),
    app_commands.Choice(name="Opus 4.6 (powerful, deep reasoning)", value="opus"),
]


class SessionManageCog(commands.Cog):
    """Cog for session listing, resume info, and CLI sync commands."""

    def __init__(
        self,
        bot: ClaudeDiscordBot,
        repo: SessionRepository,
        cli_sessions_path: str | None = None,
        settings_repo: SettingsRepository | None = None,
        runner: object | None = None,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.cli_sessions_path = cli_sessions_path
        self.settings_repo = settings_repo
        # Optional ClaudeRunner reference for reading the default model.
        # Resolved lazily from ClaudeChatCog if not provided directly.
        self._runner = runner

    async def _get_thread_style(self) -> str:
        """Get the configured thread style, defaulting to 'channel'."""
        if self.settings_repo is None:
            return THREAD_STYLE_CHANNEL
        style = await self.settings_repo.get(SETTING_SYNC_THREAD_STYLE)
        if style in _VALID_THREAD_STYLES:
            return style
        return THREAD_STYLE_CHANNEL

    async def _get_since_hours(self) -> int:
        """Get the configured since_hours filter, defaulting to 24."""
        if self.settings_repo is None:
            return _DEFAULT_SINCE_HOURS
        raw = await self.settings_repo.get(SETTING_SYNC_SINCE_HOURS)
        if raw is not None and raw.isdigit():
            return int(raw)
        return _DEFAULT_SINCE_HOURS

    async def _get_min_results(self) -> int:
        """Get the configured min_results fallback, defaulting to 10."""
        if self.settings_repo is None:
            return _DEFAULT_MIN_RESULTS
        raw = await self.settings_repo.get(SETTING_SYNC_MIN_RESULTS)
        if raw is not None and raw.isdigit():
            return int(raw)
        return _DEFAULT_MIN_RESULTS

    def _get_runner(self) -> object | None:
        """Return the runner, resolving it from ClaudeChatCog if not set directly."""
        if self._runner is not None:
            return self._runner
        chat_cog = self.bot.get_cog("ClaudeChatCog")
        if chat_cog is not None:
            return getattr(chat_cog, "runner", None)
        return None

    async def _get_effective_model(self) -> str:
        """Return the effective model: settings_repo override or runner default."""
        if self.settings_repo is not None:
            stored = await self.settings_repo.get(SETTING_CLAUDE_MODEL)
            if stored:
                return stored
        runner = self._get_runner()
        if runner is not None and hasattr(runner, "model"):
            return runner.model  # type: ignore[return-value]
        return "sonnet"

    # ── Model commands ────────────────────────────────────────────────────────

    @app_commands.command(name="model-show", description="Show the current Claude model")
    async def model_show(self, interaction: discord.Interaction) -> None:
        """Display the current global model and, if in a thread, the per-session model."""
        effective_model = await self._get_effective_model()

        embed = discord.Embed(
            title="🤖 Current Claude Model",
            color=COLOR_INFO,
        )

        # Global / default model field
        stored = await self.settings_repo.get(SETTING_CLAUDE_MODEL) if self.settings_repo else None
        runner = self._get_runner()
        runner_model = getattr(runner, "model", "sonnet") if runner else "sonnet"
        if stored:
            embed.description = (
                f"**Global override:** `{stored}`\n*(runner default: `{runner_model}`)*"
            )
        else:
            embed.description = (
                f"**Default model:** `{runner_model}`\n"
                "*(no override set — use `/model-set` to change)*"
            )

        # Per-thread session model (if inside a thread)
        if isinstance(interaction.channel, discord.Thread):
            record = await self.repo.get(interaction.channel.id)
            if record and record.model:
                embed.add_field(
                    name="This thread's last session",
                    value=f"`{record.model}`",
                    inline=False,
                )

        embed.set_footer(text=f"Effective model for new sessions: {effective_model}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="model-set", description="Change the global Claude model for new sessions"
    )  # noqa: E501
    @app_commands.describe(model="Model to use for all new Claude sessions")
    @app_commands.choices(model=_MODEL_CHOICES)
    async def model_set(self, interaction: discord.Interaction, model: str) -> None:
        """Set the global default model stored in settings_repo."""
        if model not in _VALID_MODELS:
            await interaction.response.send_message(
                f"❌ Unknown model `{model}`. Valid choices: {', '.join(sorted(_VALID_MODELS))}",
                ephemeral=True,
            )
            return

        if self.settings_repo is None:
            await interaction.response.send_message(
                "❌ Settings repository is unavailable — model cannot be persisted.",
                ephemeral=True,
            )
            return

        await self.settings_repo.set(SETTING_CLAUDE_MODEL, model)

        embed = discord.Embed(
            title="✅ Model Updated",
            description=f"Global model set to **`{model}`**.\nAll new sessions will use this model.",  # noqa: E501
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="sync-settings",
        description="View or change session sync settings",
    )
    @app_commands.describe(
        thread_style="How synced sessions appear in Discord",
        since_hours="Sync sessions active within the last N hours (default: 24)",
        min_results="Minimum sessions to sync even if outside time window (default: 10)",
    )
    @app_commands.choices(thread_style=_STYLE_CHOICES)
    async def sync_settings(
        self,
        interaction: discord.Interaction,
        thread_style: str | None = None,
        since_hours: int | None = None,
        min_results: int | None = None,
    ) -> None:
        """View or change sync settings. Without arguments, shows current settings."""
        current_style = await self._get_thread_style()
        current_hours = await self._get_since_hours()
        current_min = await self._get_min_results()
        updated = False

        if thread_style is not None and thread_style in _VALID_THREAD_STYLES:
            if self.settings_repo is not None:
                await self.settings_repo.set(SETTING_SYNC_THREAD_STYLE, thread_style)
            current_style = thread_style
            updated = True

        if since_hours is not None and since_hours >= 0:
            if self.settings_repo is not None:
                await self.settings_repo.set(SETTING_SYNC_SINCE_HOURS, str(since_hours))
            current_hours = since_hours
            updated = True

        if min_results is not None and min_results >= 0:
            if self.settings_repo is not None:
                await self.settings_repo.set(SETTING_SYNC_MIN_RESULTS, str(min_results))
            current_min = min_results
            updated = True

        style_desc = {
            THREAD_STYLE_CHANNEL: (
                "\U0001f4c1 **Channel threads** — threads appear in the Threads panel, "
                "keeping the main channel clean"
            ),
            THREAD_STYLE_MESSAGE: (
                "\U0001f4ac **Message threads** — each session posts a summary card "
                "in the channel with a thread attached"
            ),
        }

        hours_desc = (
            f"\U0001f552 **{current_hours}h** — sessions active within the last "
            f"{current_hours} hour(s)"
            if current_hours > 0
            else "\U0001f552 **No time filter** — all sessions considered"
        )

        min_desc = (
            f"\U0001f4ca **{current_min}** — if fewer than {current_min} sessions "
            f"match the time filter, fill up to {current_min} from most recent"
            if current_min > 0
            else "\U0001f4ca **No minimum** — strict time filter only"
        )

        embed = discord.Embed(
            title="\u2699\ufe0f Sync Settings",
            description=(
                f"**Thread style**: {current_style}\n"
                f"{style_desc.get(current_style, '')}\n\n"
                f"**Since hours**: {current_hours}\n"
                f"{hours_desc}\n\n"
                f"**Min results**: {current_min}\n"
                f"{min_desc}"
            ),
            color=COLOR_SUCCESS if updated else COLOR_INFO,
        )
        if updated:
            embed.set_footer(text="Setting updated! New syncs will use this style.")

        await interaction.response.send_message(embed=embed)

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

        thread_style = await self._get_thread_style()
        since_hours = await self._get_since_hours()
        min_results = await self._get_min_results()

        # Run CPU/IO-heavy scan in a thread to avoid blocking the event loop
        cli_sessions = await asyncio.to_thread(
            scan_cli_sessions,
            self.cli_sessions_path,
            since_hours=since_hours,
            min_results=min_results,
        )
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

            # Create thread based on configured style
            thread = await self._create_sync_thread(channel, cli_session, thread_name, thread_style)

            # Save to DB
            await self.repo.save(
                thread_id=thread.id,
                session_id=cli_session.session_id,
                working_dir=cli_session.working_dir,
                origin="cli",
                summary=cli_session.summary,
            )

            # Post info embed inside the thread (for channel-style threads
            # this is the main content; for message-style the embed is on
            # the parent message so we skip the duplicate here)
            if thread_style == THREAD_STYLE_CHANNEL:
                info_embed = discord.Embed(
                    title="\U0001f5a5\ufe0f Imported CLI Session",
                    description=(
                        f"This thread is linked to a Claude Code CLI session.\n"
                        f"Reply here to continue the conversation.\n\n"
                        f"```\nclaude --resume {cli_session.session_id}\n```"
                    ),
                    color=COLOR_INFO,
                )
                if cli_session.working_dir:
                    info_embed.add_field(
                        name="Working Directory",
                        value=f"`{cli_session.working_dir}`",
                        inline=True,
                    )
                if cli_session.timestamp:
                    info_embed.add_field(
                        name="Created", value=cli_session.timestamp[:10], inline=True
                    )
                info_embed.set_footer(text=f"Session: {cli_session.session_id[:8]}...")
                await thread.send(embed=info_embed)

            # Post recent conversation messages for context
            await self._post_recent_messages(thread, cli_session.session_id)

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

    async def _create_sync_thread(
        self,
        channel: discord.TextChannel,
        cli_session: CliSession,
        thread_name: str,
        style: str,
    ) -> discord.Thread:
        """Create a thread using the configured style.

        - channel: Creates a standalone thread in the Threads panel.
        - message: Posts a summary embed, then creates a thread from it.
        """
        if style == THREAD_STYLE_MESSAGE:
            embed = discord.Embed(
                title=f"\U0001f5a5\ufe0f {thread_name[:80]}",
                description=f"```\nclaude --resume {cli_session.session_id}\n```",
                color=COLOR_INFO,
            )
            if cli_session.working_dir:
                dir_short = cli_session.working_dir.rsplit("/", 1)[-1]
                embed.add_field(name="Directory", value=f"`{dir_short}`", inline=True)
            if cli_session.timestamp:
                embed.add_field(name="Created", value=cli_session.timestamp[:10], inline=True)
            embed.set_footer(text=f"Session: {cli_session.session_id[:8]}...")

            summary_msg = await channel.send(embed=embed)
            return await summary_msg.create_thread(name=f"\U0001f5a5 {thread_name}")

        # Default: channel thread
        return await channel.create_thread(
            name=f"\U0001f5a5 {thread_name}",
            type=discord.ChannelType.public_thread,
        )

    async def _post_recent_messages(self, thread: discord.Thread, session_id: str) -> None:
        """Post recent conversation messages inside the thread for context."""
        assert self.cli_sessions_path is not None  # Caller ensures this
        recent = await asyncio.to_thread(
            extract_recent_messages,
            self.cli_sessions_path,
            session_id,
            count=6,
            max_content_len=500,
        )
        if not recent:
            return

        lines: list[str] = []
        for msg in recent:
            if msg.role == "user":
                lines.append(f"**You:** {msg.content}")
            else:
                lines.append(f"**Claude:** {msg.content}")

        # Split into chunks that fit Discord's 2000 char limit
        chunk = ""
        for line in lines:
            candidate = f"{chunk}\n\n{line}" if chunk else line
            if len(candidate) > 1900:
                if chunk:
                    await thread.send(chunk)
                chunk = line[:1900]
            else:
                chunk = candidate
        if chunk:
            await thread.send(chunk)

    # ------------------------------------------------------------------
    # Worktree commands
    # ------------------------------------------------------------------

    def _get_worktree_manager(self) -> WorktreeManager | None:
        """Return the WorktreeManager from the bot, if configured."""
        return getattr(self.bot, "worktree_manager", None)

    @app_commands.command(
        name="worktree-list",
        description="List all active Claude Code session worktrees",
    )
    async def worktree_list(self, interaction: discord.Interaction) -> None:
        """Show all session worktrees (branch ``session/\\d+``) and their status."""
        wm = self._get_worktree_manager()
        if wm is None:
            await interaction.response.send_message(
                "❌ Worktree manager is not configured.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        import asyncio

        worktrees = await asyncio.to_thread(wm.find_session_worktrees)

        if not worktrees:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🌲 Session Worktrees",
                    description="No session worktrees found.",
                    color=COLOR_INFO,
                )
            )
            return

        from ..worktree import _is_clean  # noqa: PLC0415

        embed = discord.Embed(
            title=f"🌲 Session Worktrees ({len(worktrees)})",
            color=COLOR_INFO,
        )
        for wt in worktrees:
            clean = await asyncio.to_thread(_is_clean, wt.path)
            status = "✅ clean" if clean else "⚠️ dirty"
            name = f"`wt-{wt.thread_id}`"
            value = f"Branch: `{wt.branch}`\nRepo: `{wt.main_repo or 'unknown'}`\nStatus: {status}"
            embed.add_field(name=name, value=value, inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="worktree-cleanup",
        description="Remove clean orphaned session worktrees",
    )
    @app_commands.describe(
        dry_run="Preview what would be removed without actually removing anything",
    )
    async def worktree_cleanup(
        self,
        interaction: discord.Interaction,
        dry_run: bool = False,
    ) -> None:
        """Remove session worktrees that have no active session and are clean."""
        wm = self._get_worktree_manager()
        if wm is None:
            await interaction.response.send_message(
                "❌ Worktree manager is not configured.", ephemeral=True
            )
            return

        await interaction.response.defer()

        import asyncio

        # Determine active thread IDs from the session registry
        active_ids: set[int] = set()
        if hasattr(self.bot, "session_registry"):
            active_ids = {s.thread_id for s in self.bot.session_registry.list_active()}

        if dry_run:
            # Just list what would be removed
            worktrees = await asyncio.to_thread(wm.find_session_worktrees)
            from ..worktree import _is_clean  # noqa: PLC0415

            candidates = []
            skipped = []
            for wt in worktrees:
                if wt.thread_id in active_ids:
                    skipped.append((wt, "session is active"))
                    continue
                clean = await asyncio.to_thread(_is_clean, wt.path)
                if clean:
                    candidates.append(wt)
                else:
                    skipped.append((wt, "dirty"))

            embed = discord.Embed(
                title="🌲 Worktree Cleanup — Dry Run",
                color=COLOR_INFO,
            )
            if candidates:
                embed.add_field(
                    name=f"Would remove ({len(candidates)})",
                    value="\n".join(f"`{wt.path}`" for wt in candidates) or "—",
                    inline=False,
                )
            if skipped:
                embed.add_field(
                    name=f"Would skip ({len(skipped)})",
                    value="\n".join(f"`{wt.path}` — {reason}" for wt, reason in skipped) or "—",
                    inline=False,
                )
            if not candidates and not skipped:
                embed.description = "No session worktrees found."
            embed.set_footer(text="Re-run without dry_run=True to actually remove.")
            await interaction.followup.send(embed=embed)
            return

        results = await asyncio.to_thread(wm.cleanup_orphaned, active_ids)

        removed = [r for r in results if r.removed]
        dirty = [r for r in results if not r.removed and "uncommitted changes" in r.reason]
        other_skipped = [
            r
            for r in results
            if not r.removed
            and "uncommitted changes" not in r.reason
            and r.reason != "session is still active"
        ]

        color = COLOR_SUCCESS if removed else COLOR_INFO
        if dirty:
            color = COLOR_TOOL

        embed = discord.Embed(
            title="🌲 Worktree Cleanup Complete",
            color=color,
        )
        embed.add_field(
            name=f"✅ Removed ({len(removed)})",
            value="\n".join(f"`{r.path}`" for r in removed) or "—",
            inline=False,
        )
        if dirty:
            embed.add_field(
                name=f"⚠️ Dirty — not removed ({len(dirty)})",
                value="\n".join(f"`{r.path}`" for r in dirty) or "—",
                inline=False,
            )
        if other_skipped:
            embed.add_field(
                name=f"ℹ️ Skipped ({len(other_skipped)})",
                value="\n".join(f"`{r.path}` — {r.reason}" for r in other_skipped) or "—",
                inline=False,
            )

        await interaction.followup.send(embed=embed)
