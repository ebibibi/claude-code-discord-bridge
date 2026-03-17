"""dept_responder.py — TechForward department auto-session Cog

When a task is delegated to a department channel (typically by the bot itself
acting as CEO室 or another department), this Cog automatically starts a Claude
Code session with the appropriate department role.

This solves the problem where delegated tasks go unanswered because no Claude
Code session is running in the target department.

Trigger conditions:
    - Bot's own message in a department channel (delegation from another session)
    - Bot's own message as the first message in a new thread in a department channel

Loop prevention:
    - Tracks threads it has already started sessions in
    - Ignores messages in threads where a department session is already running
    - Only triggers on messages that contain delegation keywords

Configuration (environment variables):
    DEPT_RESPONDER_ENABLED   Set to "0" or "false" to disable. Defaults to enabled.
"""

from __future__ import annotations

import logging
import os
import re

import discord
from discord.ext import commands

from claude_discord.cogs._run_helper import run_claude_with_config
from claude_discord.cogs.run_config import RunConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_enabled_raw = os.environ.get("DEPT_RESPONDER_ENABLED", "1").strip().lower()
ENABLED = _enabled_raw not in ("0", "false", "no")

# Department channel IDs → department metadata
DEPARTMENTS: dict[int, dict] = {
    1483460916572979233: {
        "name": "秘書室",
        "role": "secretary",
        "description": "依頼の受付、メモ整理、今日やること整理、週次レビュー下書き",
    },
    1483460920024760437: {
        "name": "営業部",
        "role": "sales-alliance",
        "description": "Dream 30の候補整理、企業調査、提案仮説、営業・提携の下準備",
    },
    1483460923162103838: {
        "name": "開発部",
        "role": "dev-os",
        "description": "A/C案件を高速・高品質に回すためのSDD型開発OSを整備する",
    },
    1483460926643372052: {
        "name": "情報収集部",
        "role": "intelligence",
        "description": "EC業界ニュース・競合動向・技術トレンドを収集し、経営判断に使える情報に変換する",
    },
    1483460929222868994: {
        "name": "財務部",
        "role": "finance",
        "description": "資金繰り管理、月次P/Lモニタリング、固定費最適化、入金・請求管理",
    },
    1483460933039947936: {
        "name": "戦略推進部",
        "role": "pmo",
        "description": "北極星、3ヶ月計画、論点ツリーを実行可能な成果物と今週タスクへ分解する",
    },
}

# Keywords that indicate a message is a delegation/task assignment
_DELEGATION_PATTERNS = re.compile(
    r"(依頼|委任|お願い|調査|対応|確認|報告|作成|実行|至急|タスク|してください|をお願い|に依頼)",
    re.IGNORECASE,
)

_DEPT_PROMPT = """\
You are TechForward AI - {dept_name}.
Role: {dept_description}

A task has been delegated to your department via Discord. You must handle it.

IMPORTANT:
- Read the full context of the conversation and the delegating message
- Check relevant context files before responding
- React with ✅ to the delegation message to confirm receipt
- Execute the task immediately — do not just acknowledge
- If you need information from another department, post in their channel
- Report results back in this thread
- Respond in Japanese
- Be concise and action-oriented

## Delegated message
```
{{message_text}}
```

## Channel
{{channel_name}} (ID: {{channel_id}})

## Instructions
1. React ✅ to the delegation message (message ID: {{message_id}}, channel ID: {{channel_id}})
2. Read relevant context files for your department
3. Execute the delegated task
4. Post results in this thread
"""


class DepartmentResponderCog(commands.Cog):
    """Auto-starts Claude Code sessions when tasks are delegated to department channels."""

    def __init__(self, bot: commands.Bot, runner: object, components: object) -> None:
        self.bot = bot
        self.runner = runner
        self.components = components
        # Track threads where we've already started a session (prevent loops)
        self._active_threads: set[int] = set()

    def _get_department(self, channel: discord.abc.Messageable) -> dict | None:
        """Return department metadata if the channel is a department channel."""
        channel_id = getattr(channel, "id", None)
        if channel_id in DEPARTMENTS:
            return DEPARTMENTS[channel_id]

        # Check if it's a thread in a department channel
        if isinstance(channel, discord.Thread) and channel.parent_id in DEPARTMENTS:
            return DEPARTMENTS[channel.parent_id]

        return None

    def _is_delegation(self, content: str) -> bool:
        """Check if the message content looks like a task delegation."""
        if not content:
            return False
        return bool(_DELEGATION_PATTERNS.search(content))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Detect delegated tasks in department channels and auto-start sessions."""
        # Only respond to bot's own messages (delegations from other sessions)
        if not message.author.bot:
            return

        # Must be from our own bot
        if message.author.id != self.bot.user.id:
            return

        dept = self._get_department(message.channel)
        if dept is None:
            return

        # Skip Discord system messages
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return

        # Check if message looks like a delegation
        if not self._is_delegation(message.content):
            return

        # If this is a thread, check if we've already started a session here
        thread_id = message.channel.id if isinstance(message.channel, discord.Thread) else None
        if thread_id and thread_id in self._active_threads:
            return

        # If this is a top-level channel message, we need to create a thread
        # If it's already in a thread, check if it's the first bot message (delegation)
        if isinstance(message.channel, discord.Thread):
            # Only trigger on first bot message in the thread to avoid loops
            # Check if we sent this message as a delegation (not a response)
            if message.channel.id in self._active_threads:
                return

        logger.info(
            "DepartmentResponderCog: delegation detected in %s (dept=%s, message=%d)",
            getattr(message.channel, "name", "unknown"),
            dept["name"],
            message.id,
        )

        await self._start_department_session(message, dept)

    async def _start_department_session(
        self, message: discord.Message, dept: dict
    ) -> None:
        """Create a thread if needed and start a Claude Code session for the department."""
        if self.runner is None:
            logger.warning("DepartmentResponderCog: runner is None — cannot start")
            return

        # Determine thread
        if isinstance(message.channel, discord.Thread):
            thread = message.channel
        elif isinstance(message.channel, discord.TextChannel):
            # Create a thread on the delegation message
            thread = await message.create_thread(
                name=f"{dept['name']}: {message.content[:40]}",
                auto_archive_duration=1440,
            )
        else:
            logger.warning("DepartmentResponderCog: unsupported channel type")
            return

        # Mark this thread as active to prevent loops
        self._active_threads.add(thread.id)

        try:
            channel_name = getattr(message.channel, "name", "unknown")
            prompt = _DEPT_PROMPT.format(
                dept_name=dept["name"],
                dept_description=dept["description"],
            ).replace("{{message_text}}", message.content).replace(
                "{{channel_name}}", channel_name
            ).replace(
                "{{channel_id}}", str(message.channel.id)
            ).replace(
                "{{message_id}}", str(message.id)
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
        except Exception:
            logger.exception(
                "DepartmentResponderCog: error in dept session (dept=%s, thread=%d)",
                dept["name"],
                thread.id,
            )
        finally:
            # Keep thread in active set for a while to prevent re-triggers
            # but allow future delegations to the same thread
            # We leave it in _active_threads permanently for this bot lifecycle
            pass


async def setup(bot: commands.Bot, runner: object, components: object) -> None:
    """Entry point called by the custom Cog loader."""
    if not ENABLED:
        logger.info("DepartmentResponderCog: disabled via DEPT_RESPONDER_ENABLED=0")
        return

    await bot.add_cog(DepartmentResponderCog(bot, runner, components))
    logger.info(
        "DepartmentResponderCog loaded — monitoring %d department channels",
        len(DEPARTMENTS),
    )
