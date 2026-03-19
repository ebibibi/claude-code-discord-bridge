"""ceo_responder.py — TechForward CEO message auto-responder Cog

Watches configured Discord channels for CEO messages. When a CEO message
is detected, automatically creates a thread (if needed) and runs Claude Code
to generate an appropriate response.

Monitored channels:
    - #戦略会議室 and its threads
    - #CEO指示 forum threads
    - All department channels (#秘書室, #営業部, etc.)

Configuration (environment variables):
    CEO_USER_ID           (required) Discord user ID of the CEO.
                          If not set the Cog is silently disabled.
    CEO_RESPONDER_CHANNELS Comma-separated channel IDs to monitor.
                          Defaults to strategy-room + dept channels.
"""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

from claude_discord.cogs._run_helper import run_claude_with_config
from claude_discord.cogs.run_config import RunConfig

# Import department config for department-aware responses
from .dept_responder import DEPARTMENTS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_raw_ceo_id = os.environ.get("CEO_USER_ID", "")
CEO_USER_ID: int | None = int(_raw_ceo_id) if _raw_ceo_id else None

# Default channels to monitor (strategy room + all department channels + CEO channels)
_DEFAULT_CHANNELS = {
    1483328145380872294,  # #戦略会議室
    1483460916572979233,  # #COO室
    1483460920024760437,  # #営業部
    1483460923162103838,  # #開発部
    1483460926643372052,  # #情報収集部
    1483460929222868994,  # #財務部
    1483460933039947936,  # #戦略推進部
    1483686132364476448,  # #会長メモ
    1483328670331306014,  # #AI運用ログ
}

_raw_channels = os.environ.get("CEO_RESPONDER_CHANNELS", "")
if _raw_channels:
    MONITOR_CHANNEL_IDS: set[int] = {int(c.strip()) for c in _raw_channels.split(",") if c.strip()}
else:
    MONITOR_CHANNEL_IDS = _DEFAULT_CHANNELS

# Forum parent ID for #CEO指示
CEO_FORUM_ID = 1483348696589664408

_RESPONSE_PROMPT = """\
You are TechForward AI - CEO室. The CEO just posted a message in Discord.
Respond appropriately in the same thread/channel.

IMPORTANT:
- Read the full context of the conversation before responding
- Check context files if the question relates to company operations
- If the question requires another department, delegate via their channel
- Always react with ✅ to the CEO's message before responding
- Respond in Japanese
- Be concise and action-oriented

## CEO's message
```
{message_text}
```

## Channel
{channel_name} (ID: {channel_id})

## Instructions
1. React ✅ to the CEO's message (message ID: {message_id}, channel ID: {channel_id})
2. Analyze the CEO's message and respond appropriately
3. If delegation is needed, post to the relevant department channel
4. Post your response in the same channel/thread
"""

_DEPT_RESPONSE_PROMPT = """\
You are TechForward AI - {dept_name}. A task has been delegated to your department.
Read the delegation message and respond appropriately.

IMPORTANT:
- Read the full context of the conversation before responding
- Check relevant context files for your department
- React with ✅ to the delegation message to confirm receipt
- Execute the task immediately — do not just acknowledge
- If you need information from another department, post in their channel
- Report results back in this thread
- Respond in Japanese
- Be concise and action-oriented

## CEO's message
```
{message_text}
```

## Channel
{channel_name} (ID: {channel_id})

## Instructions
1. React ✅ to the CEO's message (message ID: {message_id}, channel ID: {channel_id})
2. Read relevant context files for your department
3. Execute the task or answer the CEO's question
4. Post results in this thread
"""


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class CEOResponderCog(commands.Cog):
    """Watches Discord channels for CEO messages and auto-responds via Claude Code."""

    def __init__(self, bot: commands.Bot, runner: object, components: object) -> None:
        self.bot = bot
        self.runner = runner
        self.components = components
        self._responding: set[int] = set()

    def _get_department(self, channel: discord.abc.Messageable) -> dict | None:
        """Return department metadata if the channel is a department channel."""
        channel_id = getattr(channel, "id", None)
        if channel_id in DEPARTMENTS:
            return DEPARTMENTS[channel_id]
        if isinstance(channel, discord.Thread) and channel.parent_id in DEPARTMENTS:
            return DEPARTMENTS[channel.parent_id]
        return None

    def _should_monitor(self, channel: discord.abc.Messageable) -> bool:
        """Check if this channel/thread should be monitored."""
        # Direct channel match
        if hasattr(channel, "id") and channel.id in MONITOR_CHANNEL_IDS:
            return True

        # Thread in monitored channel
        if isinstance(channel, discord.Thread):
            if channel.parent_id in MONITOR_CHANNEL_IDS:
                return True
            # Thread in #CEO指示 forum
            if channel.parent_id == CEO_FORUM_ID:
                return True

        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Check each incoming message; respond if from CEO in monitored channel."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Only respond to CEO
        if CEO_USER_ID is None or message.author.id != CEO_USER_ID:
            return

        # Only monitor configured channels
        if not self._should_monitor(message.channel):
            return

        # Ignore Discord system messages
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return

        # Skip if already responding to this message
        if message.id in self._responding:
            return

        self._responding.add(message.id)
        try:
            await self._respond_to_ceo(message)
        except Exception:
            logger.exception(
                "CEOResponderCog: unexpected error responding to CEO (message_id=%d)",
                message.id,
            )
        finally:
            self._responding.discard(message.id)

    async def _respond_to_ceo(self, message: discord.Message) -> None:
        """Create a thread if needed and run Claude Code to respond."""
        if self.runner is None:
            logger.warning("CEOResponderCog: runner is None — cannot start Claude")
            return

        logger.info(
            "CEOResponderCog: CEO message detected (channel=%s, message=%d)",
            getattr(message.channel, "name", "unknown"),
            message.id,
        )

        # Determine where to respond
        if isinstance(message.channel, discord.Thread):
            # Already in a thread — respond directly
            thread = message.channel
        elif isinstance(message.channel, discord.TextChannel):
            # Create a thread on the CEO's message
            thread = await message.create_thread(
                name=f"CEO: {message.content[:50]}",
                auto_archive_duration=1440,
            )
        else:
            logger.warning("CEOResponderCog: unsupported channel type — skipping")
            return

        channel_name = getattr(message.channel, "name", "unknown")

        # Use department-specific prompt when CEO posts in a department channel
        dept = self._get_department(message.channel)
        if dept:
            prompt = _DEPT_RESPONSE_PROMPT.format(
                dept_name=dept["name"],
                message_text=message.content,
                channel_name=channel_name,
                channel_id=message.channel.id,
                message_id=message.id,
            )
        else:
            prompt = _RESPONSE_PROMPT.format(
                message_text=message.content,
                channel_name=channel_name,
                channel_id=message.channel.id,
                message_id=message.id,
            )

        session_repo = getattr(self.components, "session_repo", None)
        registry = getattr(self.bot, "session_registry", None)
        lounge_repo = getattr(self.components, "lounge_repo", None)

        cloned_runner = self.runner.clone()

        await run_claude_with_config(
            RunConfig(
                thread=thread,
                runner=cloned_runner,
                prompt=prompt,
                session_id=None,
                repo=session_repo,
                registry=registry,
                lounge_repo=lounge_repo,
                chat_only=True,
            )
        )


async def setup(bot: commands.Bot, runner: object, components: object) -> None:
    """Entry point called by the custom Cog loader."""
    if CEO_USER_ID is None:
        logger.warning(
            "CEOResponderCog: CEO_USER_ID is not set — Cog disabled. "
            "Set the environment variable to enable CEO auto-response."
        )
        return

    await bot.add_cog(CEOResponderCog(bot, runner, components))
    logger.info(
        "CEOResponderCog loaded — monitoring %d channels for CEO (user_id=%d)",
        len(MONITOR_CHANNEL_IDS),
        CEO_USER_ID,
    )
