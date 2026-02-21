"""WebhookTriggerCog — Webhook message → Claude Code task execution.

Generic pattern for triggering Claude Code runs via Discord webhooks.
Useful for CI/CD pipelines (e.g. GitHub Actions → Discord → Claude Code).

Security design:
- Only processes messages with a webhook_id (ignores regular users and bots)
- Optional webhook_id allowlist for stricter access control
- Prompts are defined server-side (webhook payload only selects which trigger)
- Per-prefix asyncio.Lock prevents concurrent runs of the same trigger
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ..cogs._run_helper import run_claude_with_config
from ..cogs.run_config import RunConfig
from ..concurrency import SessionRegistry

if TYPE_CHECKING:
    from ..claude.runner import ClaudeRunner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookTrigger:
    """Configuration for a single webhook trigger.

    Attributes:
        prompt: The Claude Code prompt to execute when triggered.
        working_dir: Override ClaudeRunner's working directory.
        timeout: Override ClaudeRunner's timeout in seconds.
        allowed_tools: Override ClaudeRunner's allowed tools list.
        dangerously_skip_permissions: Whether to skip Claude Code permission checks.
    """

    prompt: str
    working_dir: str | None = None
    timeout: int = 300
    allowed_tools: list[str] | None = None
    dangerously_skip_permissions: bool = True


class WebhookTriggerCog(commands.Cog):
    """Cog that executes Claude Code tasks in response to Discord webhook messages.

    Each trigger is identified by a message prefix (e.g. "🔄 docs-sync").
    The prompt is defined server-side — the webhook only selects which trigger to fire.

    Args:
        bot: The Discord bot instance.
        runner: Base ClaudeRunner to clone for each trigger execution.
        triggers: Mapping of prefix string → WebhookTrigger configuration.
        allowed_webhook_ids: Optional set of allowed Discord webhook IDs.
            If None, all webhooks are accepted.
        channel_ids: Optional set of channel IDs to listen in.
            If None, listens in all channels.
    """

    def __init__(
        self,
        bot: commands.Bot,
        runner: ClaudeRunner,
        triggers: dict[str, WebhookTrigger],
        allowed_webhook_ids: set[int] | None = None,
        channel_ids: set[int] | None = None,
        registry: SessionRegistry | None = None,
    ) -> None:
        self.bot = bot
        self.runner = runner
        self.triggers = triggers
        self.allowed_webhook_ids = allowed_webhook_ids
        self.channel_ids = channel_ids
        self._registry = registry or getattr(bot, "session_registry", None)
        self._locks: dict[str, asyncio.Lock] = {prefix: asyncio.Lock() for prefix in triggers}
        self._active_count: int = 0

    @property
    def active_count(self) -> int:
        """Number of currently running webhook-triggered Claude sessions."""
        return self._active_count

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages, filtering for webhook triggers."""
        if not message.webhook_id:
            return

        if (
            self.allowed_webhook_ids is not None
            and message.webhook_id not in self.allowed_webhook_ids
        ):
            return

        if self.channel_ids is not None and message.channel.id not in self.channel_ids:
            return

        content = message.content.strip()
        matched_prefix: str | None = None
        matched_trigger: WebhookTrigger | None = None

        for prefix, trigger in self.triggers.items():
            if content == prefix or content.startswith(prefix):
                matched_prefix = prefix
                matched_trigger = trigger
                break

        if matched_prefix is None or matched_trigger is None:
            return

        logger.info(
            "Webhook trigger matched: prefix=%r, webhook_id=%d",
            matched_prefix,
            message.webhook_id,
        )

        lock = self._locks[matched_prefix]
        if lock.locked():
            await message.reply(f"⏳ `{matched_prefix}` is already running. Skipping.")
            return

        async with lock:
            await self._execute_trigger(message, matched_prefix, matched_trigger)

    async def _execute_trigger(
        self,
        message: discord.Message,
        prefix: str,
        trigger: WebhookTrigger,
    ) -> None:
        """Execute a matched trigger via Claude Code."""
        thread = await message.create_thread(name=prefix[:100])

        runner = self.runner.clone()
        runner.dangerously_skip_permissions = trigger.dangerously_skip_permissions
        runner.timeout_seconds = trigger.timeout
        if trigger.working_dir:
            runner.working_dir = trigger.working_dir
        if trigger.allowed_tools is not None:
            runner.allowed_tools = trigger.allowed_tools

        self._active_count += 1
        try:
            session_id = await run_claude_with_config(
                RunConfig(
                    thread=thread,
                    runner=runner,
                    repo=None,
                    prompt=trigger.prompt,
                    session_id=None,
                    status=None,
                    registry=self._registry,
                )
            )

            if session_id:
                await message.add_reaction("✅")
            else:
                await message.add_reaction("❌")
        finally:
            self._active_count -= 1
