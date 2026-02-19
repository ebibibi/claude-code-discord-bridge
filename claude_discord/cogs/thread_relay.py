"""Cross-thread relay Cog.

Provides the /relay slash command, allowing users to send a message
from one Claude thread to another. This enables multi-agent coordination
patterns — e.g. an orchestrator thread delegating to specialist threads.

UX flow:
  Thread A: /relay target:#thread-b message:"What's the auth endpoint?"
  Thread B: [📨 Relayed from #thread-a embed] → Claude processes message
  Thread A: [📤 Relayed to #thread-b confirmation]
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..claude.runner import ClaudeRunner
from ..concurrency import SessionRegistry
from ..database.repository import SessionRepository
from ..discord_ui.embeds import error_embed, relay_received_embed, relay_sent_embed
from ..discord_ui.views import StopView
from ._run_helper import run_claude_in_thread

if TYPE_CHECKING:
    from ..bot import ClaudeDiscordBot

logger = logging.getLogger(__name__)

# Prefix injected into the prompt so Claude knows the message was relayed
_RELAY_PREFIX_TMPL = "[Relayed from #{source_name}]\n\n"


class ThreadRelayCog(commands.Cog):
    """Cog that enables cross-thread message relay between Claude sessions."""

    def __init__(
        self,
        bot: ClaudeDiscordBot,
        repo: SessionRepository,
        runner: ClaudeRunner,
        allowed_user_ids: set[int] | None = None,
        registry: SessionRegistry | None = None,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.runner = runner
        self._allowed_user_ids = allowed_user_ids
        self._registry = registry or getattr(bot, "session_registry", None)

    @app_commands.command(
        name="relay",
        description="Send a message to another Claude thread, triggering its session",
    )
    @app_commands.describe(
        target="The target thread to relay the message to",
        message="The message to send to the target thread",
    )
    async def relay(
        self,
        interaction: discord.Interaction,
        target: discord.Thread,
        message: str,
    ) -> None:
        """Relay a message to another thread's Claude session."""
        # Authorization check
        if self._allowed_user_ids is not None and interaction.user.id not in self._allowed_user_ids:
            await interaction.response.send_message(
                "You are not authorized to use this command.", ephemeral=True
            )
            return

        # Must be used from inside a thread
        source = interaction.channel
        if not isinstance(source, discord.Thread):
            await interaction.response.send_message(
                "This command must be used from inside a Claude thread.", ephemeral=True
            )
            return

        # Guard against self-relay
        if target.id == source.id:
            await interaction.response.send_message(
                "Cannot relay a message to the same thread.", ephemeral=True
            )
            return

        # Target must be a thread under the configured Claude channel
        if target.parent_id != self.bot.channel_id:
            await interaction.response.send_message(
                "The target must be a thread in the Claude channel.", ephemeral=True
            )
            return

        # Acknowledge immediately so Discord doesn't time out
        await interaction.response.defer()

        # Post attribution embed in the target thread so both humans and context are clear
        try:
            await target.send(embed=relay_received_embed(source, message))
        except discord.HTTPException:
            logger.warning("Failed to post relay attribution in target thread %d", target.id)

        # Look up the target thread's existing session (resume if present)
        record = await self.repo.get(target.id)
        session_id = record.session_id if record else None

        # Build the prompt with attribution prefix so Claude understands the relay context
        prompt = _RELAY_PREFIX_TMPL.format(source_name=source.name) + message

        # Launch Claude in the target thread asynchronously
        asyncio.create_task(
            self._run_relay_in_target(target, prompt, session_id),
            name=f"relay-{source.id}->{target.id}",
        )

        # Confirm in the source thread immediately
        await interaction.followup.send(embed=relay_sent_embed(target, message))

    async def _run_relay_in_target(
        self,
        target: discord.Thread,
        prompt: str,
        session_id: str | None,
    ) -> None:
        """Run Claude in the target thread as part of a relay.

        Manages the stop button lifecycle and handles unexpected errors
        so they surface in the target thread rather than disappearing silently.
        """
        runner = self.runner.clone()
        stop_view = StopView(runner)
        stop_msg = await target.send("-# ⏺ Session running (relayed)", view=stop_view)

        try:
            await run_claude_in_thread(
                thread=target,
                runner=runner,
                repo=self.repo,
                prompt=prompt,
                session_id=session_id,
                status=None,
                registry=self._registry,
            )
        except Exception:
            logger.exception("Unexpected error in relay to thread %d", target.id)
            with contextlib.suppress(discord.HTTPException):
                await target.send(embed=error_embed("Relay failed with an unexpected error."))
        finally:
            await stop_view.disable(stop_msg)
