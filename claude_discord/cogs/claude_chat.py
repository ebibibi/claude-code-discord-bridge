"""Claude Code chat Cog.

Handles the core message flow:
1. User sends message in the configured channel
2. Bot creates a thread (or continues in existing thread)
3. Claude Code CLI is invoked with stream-json output
4. Status reactions and tool embeds are posted in real-time
5. Final response is posted to the thread
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..claude.runner import ClaudeRunner
from ..concurrency import SessionRegistry
from ..coordination.service import CoordinationService
from ..database.ask_repo import PendingAskRepository
from ..database.lounge_repo import LoungeRepository
from ..database.repository import SessionRepository
from ..database.resume_repo import PendingResumeRepository
from ..discord_ui.embeds import stopped_embed
from ..discord_ui.status import StatusManager
from ..discord_ui.thread_dashboard import ThreadState, ThreadStatusDashboard
from ..discord_ui.views import StopView
from ._run_helper import run_claude_with_config
from .run_config import RunConfig

if TYPE_CHECKING:
    from ..bot import ClaudeDiscordBot

logger = logging.getLogger(__name__)

# Attachment filtering constants
_ALLOWED_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
)
_MAX_ATTACHMENT_BYTES = 50_000  # 50 KB per file
_MAX_TOTAL_BYTES = 100_000  # 100 KB across all attachments
_MAX_ATTACHMENTS = 5


class ClaudeChatCog(commands.Cog):
    """Cog that handles Claude Code conversations via Discord threads."""

    def __init__(
        self,
        bot: ClaudeDiscordBot,
        repo: SessionRepository,
        runner: ClaudeRunner,
        max_concurrent: int = 3,
        allowed_user_ids: set[int] | None = None,
        registry: SessionRegistry | None = None,
        dashboard: ThreadStatusDashboard | None = None,
        coordination: CoordinationService | None = None,
        ask_repo: PendingAskRepository | None = None,
        lounge_repo: LoungeRepository | None = None,
        resume_repo: PendingResumeRepository | None = None,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.runner = runner
        self._max_concurrent = max_concurrent
        self._allowed_user_ids = allowed_user_ids
        self._registry = registry or getattr(bot, "session_registry", None)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_runners: dict[int, ClaudeRunner] = {}
        # Dashboard may be None until bot is ready; resolved lazily in _get_dashboard()
        self._dashboard = dashboard
        # Coordination service resolved lazily from bot if not supplied directly
        self._coordination = coordination
        # For AskUserQuestion persistence across restarts
        self._ask_repo = ask_repo or getattr(bot, "ask_repo", None)
        # AI Lounge repo (optional — lounge disabled when None)
        self._lounge_repo = lounge_repo or getattr(bot, "lounge_repo", None)
        # Pending resume repo (optional — startup resume disabled when None)
        self._resume_repo = resume_repo or getattr(bot, "resume_repo", None)

    @property
    def active_session_count(self) -> int:
        """Number of Claude sessions currently running in this cog."""
        return len(self._active_runners)

    @property
    def active_count(self) -> int:
        """Alias for active_session_count (satisfies DrainAware protocol)."""
        return self.active_session_count

    def _get_dashboard(self) -> ThreadStatusDashboard | None:
        """Return the dashboard, resolving it from the bot if not yet set."""
        if self._dashboard is None:
            self._dashboard = getattr(self.bot, "thread_dashboard", None)
        return self._dashboard

    def _get_coordination(self) -> CoordinationService:
        """Return the coordination service (zero-config: auto-creates from env if needed).

        Priority:
        1. Explicitly supplied via constructor or bot.coordination attribute
        2. Auto-created from COORDINATION_CHANNEL_ID env var (no consumer wiring needed)
        3. No-op service when env var is unset
        """
        if self._coordination is None:
            existing = getattr(self.bot, "coordination", None)
            if existing is not None:
                self._coordination = existing
            else:
                channel_id_str = os.getenv("COORDINATION_CHANNEL_ID", "")
                channel_id = int(channel_id_str) if channel_id_str.isdigit() else None
                self._coordination = CoordinationService(self.bot, channel_id)
        return self._coordination

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Authorization check — if allowed_user_ids is set, only those users
        # can invoke Claude.  When unset, channel-level Discord permissions
        # are the only gate (suitable for private servers).
        if self._allowed_user_ids is not None and message.author.id not in self._allowed_user_ids:
            return

        # Check if message is in the configured channel (new conversation)
        if message.channel.id == self.bot.channel_id:
            await self._handle_new_conversation(message)
            return

        # Check if message is in a thread under the configured channel
        if (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == self.bot.channel_id
        ):
            await self._handle_thread_reply(message)

    @app_commands.command(name="stop", description="Stop the active session (session is preserved)")
    async def stop_session(self, interaction: discord.Interaction) -> None:
        """Stop the active Claude run without clearing the session.

        Unlike /clear, this preserves the session ID so the user can
        resume by sending a new message.
        """
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This command can only be used in a Claude chat thread.", ephemeral=True
            )
            return

        runner = self._active_runners.get(interaction.channel.id)
        if not runner:
            await interaction.response.send_message(
                "No active session is running in this thread.", ephemeral=True
            )
            return

        await runner.interrupt()
        # _active_runners cleanup is handled by _run_claude's finally block.
        # We intentionally do NOT delete from the session DB so the user can resume.
        await interaction.response.send_message(embed=stopped_embed())

    @app_commands.command(name="clear", description="Reset the Claude Code session for this thread")
    async def clear_session(self, interaction: discord.Interaction) -> None:
        """Reset the session for the current thread."""
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This command can only be used in a Claude chat thread.", ephemeral=True
            )
            return

        # Kill active runner if any
        runner = self._active_runners.get(interaction.channel.id)
        if runner:
            await runner.kill()
            del self._active_runners[interaction.channel.id]

        deleted = await self.repo.delete(interaction.channel.id)
        if deleted:
            await interaction.response.send_message(
                "\U0001f504 Session cleared. Next message will start a fresh session."
            )
        else:
            await interaction.response.send_message(
                "No active session found for this thread.", ephemeral=True
            )

    async def _handle_new_conversation(self, message: discord.Message) -> None:
        """Create a new thread and start a Claude Code session."""
        thread_name = message.content[:100] if message.content else "Claude Chat"
        thread = await message.create_thread(name=thread_name)
        prompt = await self._build_prompt(message)
        await self._run_claude(message, thread, prompt, session_id=None)

    async def spawn_session(
        self,
        channel: discord.TextChannel,
        prompt: str,
        thread_name: str | None = None,
        session_id: str | None = None,
    ) -> discord.Thread:
        """Create a new thread and start a Claude Code session without a user message.

        This is the API-initiated equivalent of ``_handle_new_conversation``.
        It bypasses the ``on_message`` bot-author guard, enabling programmatic
        spawning of Claude sessions (e.g. from ``POST /api/spawn``).

        A seed message is posted inside the new thread so that ``StatusManager``
        has a concrete ``discord.Message`` to attach reaction-emoji status to.

        Args:
            channel: The parent text channel in which to create the thread.
            prompt: The instruction to send to Claude Code.
            thread_name: Optional thread title; defaults to the first 100 chars
                of *prompt*.
            session_id: Optional Claude session ID to resume via ``--resume``.
                        When supplied the new Claude process continues the
                        previous conversation rather than starting fresh.

        Returns:
            The newly created :class:`discord.Thread`.
        """
        name = (thread_name or prompt)[:100]
        thread = await channel.create_thread(
            name=name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=60,
        )
        # Post the prompt so StatusManager has a Message to add reactions to.
        seed_message = await thread.send(prompt)
        # Run Claude in the background so /api/spawn returns immediately.
        # The caller gets the thread reference without waiting for Claude to finish.
        asyncio.create_task(self._run_claude(seed_message, thread, prompt, session_id=session_id))
        return thread

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Resume any Claude sessions that marked themselves for restart-resume.

        Called each time the bot connects to Discord (including reconnects).
        Only pending resumes within the TTL window (default 5 minutes) are
        processed; older entries are silently discarded by the repository.

        Safety guarantees:
        - Each row is **deleted before** spawning Claude so that even a
          crash during spawn cannot cause a double-resume.
        - The TTL prevents stale markers from triggering after a long
          downtime or accidental second restart.
        - A resume failure (e.g. channel not found) is logged and skipped
          gracefully — it never prevents the bot from becoming ready.
        """
        if self._resume_repo is None:
            return

        pending = await self._resume_repo.get_pending()
        if not pending:
            return

        logger.info("Found %d pending session resume(s) on startup", len(pending))

        for entry in pending:
            # Delete FIRST — prevents double-resume even if spawn fails
            await self._resume_repo.delete(entry.id)

            thread_id = entry.thread_id
            try:
                raw = self.bot.get_channel(thread_id)
                if raw is None:
                    raw = await self.bot.fetch_channel(thread_id)
            except Exception:
                logger.warning(
                    "Pending resume: thread %d not found, skipping", thread_id, exc_info=True
                )
                continue

            if not isinstance(raw, discord.Thread):
                logger.warning("Pending resume: channel %d is not a Thread, skipping", thread_id)
                continue

            thread = raw
            parent = thread.parent
            if not isinstance(parent, discord.TextChannel):
                logger.warning(
                    "Pending resume: thread %d has no TextChannel parent, skipping", thread_id
                )
                continue

            resume_prompt = entry.resume_prompt or (
                "ボットが再起動から復帰しました。"
                "前の作業の続きを確認し、必要な残作業を完了してください。"
            )

            logger.info(
                "Resuming session in thread %d (session_id=%s, reason=%s)",
                thread_id,
                entry.session_id,
                entry.reason,
            )
            try:
                # Post directly into the existing thread — no new thread needed
                seed_message = await thread.send(
                    f"🔄 **Bot が再起動から復帰しました。**\n{resume_prompt}"
                )
                asyncio.create_task(
                    self._run_claude(
                        seed_message,
                        thread,
                        resume_prompt,
                        session_id=entry.session_id,
                    )
                )
            except Exception:
                logger.error("Failed to resume session in thread %d", thread_id, exc_info=True)

    async def _handle_thread_reply(self, message: discord.Message) -> None:
        """Continue a Claude Code session in an existing thread."""
        thread = message.channel
        assert isinstance(thread, discord.Thread)

        record = await self.repo.get(thread.id)
        session_id = record.session_id if record else None
        prompt = await self._build_prompt(message)
        await self._run_claude(message, thread, prompt, session_id=session_id)

    async def _build_prompt(self, message: discord.Message) -> str:
        """Build the prompt string, appending eligible text attachments.

        Only plain-text MIME types are included (text/*, application/json,
        application/xml).  Binary files and attachments exceeding the size
        limits are silently skipped — never raise an error to the user.
        """
        prompt = message.content or ""
        if not message.attachments:
            return prompt

        total_bytes = 0
        sections: list[str] = []
        for attachment in message.attachments[:_MAX_ATTACHMENTS]:
            if attachment.size > _MAX_ATTACHMENT_BYTES:
                logger.debug(
                    "Skipping attachment %s: too large (%d bytes)",
                    attachment.filename,
                    attachment.size,
                )
                continue
            content_type = attachment.content_type or ""
            if not content_type.startswith(_ALLOWED_MIME_PREFIXES):
                logger.debug(
                    "Skipping attachment %s: unsupported type %s",
                    attachment.filename,
                    content_type,
                )
                continue
            total_bytes += attachment.size
            if total_bytes > _MAX_TOTAL_BYTES:
                logger.debug("Stopping attachment processing: total size exceeded")
                break
            try:
                data = await attachment.read()
                text = data.decode("utf-8", errors="replace")
                sections.append(f"\n\n--- Attached file: {attachment.filename} ---\n{text}")
            except Exception:
                logger.debug("Failed to read attachment %s", attachment.filename, exc_info=True)
                continue

        return prompt + "".join(sections)

    async def _run_claude(
        self,
        user_message: discord.Message,
        thread: discord.Thread,
        prompt: str,
        session_id: str | None,
    ) -> None:
        """Execute Claude Code CLI and stream results to the thread."""
        if self._semaphore.locked():
            await thread.send(
                f"\u23f3 Waiting for a free session slot... "
                f"({self._max_concurrent} max sessions running)"
            )

        async with self._semaphore:
            dashboard = self._get_dashboard()
            coordination = self._get_coordination()
            description = prompt[:100].replace("\n", " ")

            # Mark thread as PROCESSING when Claude starts
            if dashboard is not None:
                await dashboard.set_state(
                    thread.id,
                    ThreadState.PROCESSING,
                    description,
                    thread=thread,
                )

            status = StatusManager(user_message)
            await status.set_thinking()

            runner = self.runner.clone(thread_id=thread.id)
            self._active_runners[thread.id] = runner

            stop_view = StopView(runner)
            stop_msg = await thread.send("-# ⏺ Session running", view=stop_view)
            stop_view.set_message(stop_msg)

            try:
                await run_claude_with_config(
                    RunConfig(
                        thread=thread,
                        runner=runner,
                        repo=self.repo,
                        prompt=prompt,
                        session_id=session_id,
                        status=status,
                        registry=self._registry,
                        ask_repo=self._ask_repo,
                        lounge_repo=self._lounge_repo,
                        stop_view=stop_view,
                    )
                )
            finally:
                await stop_view.disable()
                self._active_runners.pop(thread.id, None)

                # Announce session end to coordination channel (no-op if unconfigured)
                await coordination.post_session_end(thread)

                # Transition to WAITING_INPUT so owner knows a reply is needed
                if dashboard is not None:
                    await dashboard.set_state(
                        thread.id,
                        ThreadState.WAITING_INPUT,
                        description,
                        thread=thread,
                    )
