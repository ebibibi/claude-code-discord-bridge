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
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..claude.runner import ClaudeRunner
from ..concurrency import SessionRegistry
from ..database.repository import SessionRepository
from ..discord_ui.embeds import stopped_embed
from ..discord_ui.status import StatusManager
from ._run_helper import run_claude_in_thread

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
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.runner = runner
        self._max_concurrent = max_concurrent
        self._allowed_user_ids = allowed_user_ids
        self._registry = registry or getattr(bot, "session_registry", None)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_runners: dict[int, ClaudeRunner] = {}

    @property
    def active_session_count(self) -> int:
        """Number of Claude sessions currently running in this cog."""
        return len(self._active_runners)

    @property
    def active_count(self) -> int:
        """Alias for active_session_count (satisfies DrainAware protocol)."""
        return self.active_session_count

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

        await runner.kill()
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
            status = StatusManager(user_message)
            await status.set_thinking()

            runner = self.runner.clone()
            self._active_runners[thread.id] = runner

            try:
                await run_claude_in_thread(
                    thread=thread,
                    runner=runner,
                    repo=self.repo,
                    prompt=prompt,
                    session_id=session_id,
                    status=status,
                    registry=self._registry,
                )
            finally:
                self._active_runners.pop(thread.id, None)
