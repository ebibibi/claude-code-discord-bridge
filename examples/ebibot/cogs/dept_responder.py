"""dept_responder.py — TechForward department auto-session Cog

When a task is delegated to a department channel, this Cog automatically starts
a Claude Code session with the appropriate department role.

Trigger conditions:
    - Any bot message in a department channel with delegation keywords
    - CEO (human) message in a department channel
    - Scheduled task kick messages

Loop prevention:
    - Tracks threads it has already started sessions in
    - Ignores messages from the department's OWN bot (to avoid self-loops)
    - Rate-limits: max 1 session per department channel per 5 minutes

Configuration (environment variables):
    DEPT_RESPONDER_ENABLED   Set to "0" or "false" to disable. Defaults to enabled.
"""

from __future__ import annotations

import logging
import os
import re
import time

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

# CEO (human) user ID — messages from CEO always trigger a department session
_raw_ceo_id = os.environ.get("CEO_USER_ID", "")
CEO_USER_ID: int | None = int(_raw_ceo_id) if _raw_ceo_id else None

# All known department bot IDs (messages from these bots in OTHER dept channels = delegation)
DEPT_BOT_IDS: set[int] = {
    1483273974585757890,  # TechForward AI - CEO (bridge bot)
    1483446901574603047,  # TechForward AI - COO室
    1483447554032144446,  # TechForward AI - 営業部
    1483447907272102018,  # TechForward AI - 開発部
    1483448223552114841,  # TechForward AI - 情報収集部
    1483448500644745266,  # TechForward AI - 財務部
    1483448786901532734,  # TechForward AI - 戦略推進部
}

# Rate limit: minimum seconds between sessions per department channel
RATE_LIMIT_SECONDS = int(os.environ.get("DEPT_RATE_LIMIT_SECONDS", "300"))

# Department channel IDs → department metadata
DEPARTMENTS: dict[int, dict] = {
    1483460916572979233: {
        "name": "COO室",
        "role": "coo",
        "bot_id": 1483446901574603047,
        "description": "依頼の受付、メモ整理、今日やること整理、週次レビュー下書き",
    },
    1483460920024760437: {
        "name": "営業部",
        "role": "sales-alliance",
        "bot_id": 1483447554032144446,
        "description": "Dream 30の候補整理、企業調査、提案仮説、営業・提携の下準備",
    },
    1483460923162103838: {
        "name": "開発部",
        "role": "dev-os",
        "bot_id": 1483447907272102018,
        "description": "A/C案件を高速・高品質に回すためのSDD型開発OSを整備する",
    },
    1483460926643372052: {
        "name": "情報収集部",
        "role": "intelligence",
        "bot_id": 1483448223552114841,
        "description": "EC業界ニュース・競合動向・技術トレンドを収集し、経営判断に使える情報に変換する",
    },
    1483460929222868994: {
        "name": "財務部",
        "role": "finance",
        "bot_id": 1483448500644745266,
        "description": "資金繰り管理、月次P/Lモニタリング、固定費最適化、入金・請求管理",
    },
    1483460933039947936: {
        "name": "戦略推進部",
        "role": "pmo",
        "bot_id": 1483448786901532734,
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
        # Rate limit: channel_id → last session start timestamp
        self._last_session: dict[int, float] = {}

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

    def _is_from_dept_own_bot(self, message: discord.Message, dept: dict) -> bool:
        """Check if the message is from the department's own bot (self-loop)."""
        return message.author.id == dept.get("bot_id")

    def _is_rate_limited(self, channel_id: int) -> bool:
        """Check if the department channel is rate-limited."""
        last = self._last_session.get(channel_id, 0)
        return (time.monotonic() - last) < RATE_LIMIT_SECONDS

    def _should_trigger(self, message: discord.Message, dept: dict) -> bool:
        """Determine if this message should trigger a department session."""
        # Case 1: CEO (human) posts in department channel → always trigger
        if CEO_USER_ID and message.author.id == CEO_USER_ID:
            return True

        # Case 2: A bot posts in department channel
        if message.author.bot:
            # Never trigger for the department's own bot (self-loop prevention)
            if self._is_from_dept_own_bot(message, dept):
                return False

            # Trigger for bridge bot or any known dept bot with delegation keywords
            if message.author.id in DEPT_BOT_IDS or message.author.id == self.bot.user.id:
                return self._is_delegation(message.content)

        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Detect delegated tasks in department channels and auto-start sessions."""
        dept = self._get_department(message.channel)
        if dept is None:
            return

        # Skip Discord system messages
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return

        # Determine if we should trigger
        if not self._should_trigger(message, dept):
            return

        # If this is a thread, check if we've already started a session here
        thread_id = message.channel.id if isinstance(message.channel, discord.Thread) else None
        if thread_id and thread_id in self._active_threads:
            return

        # Rate limit per department channel
        parent_channel_id = (
            message.channel.parent_id
            if isinstance(message.channel, discord.Thread)
            else message.channel.id
        )
        if self._is_rate_limited(parent_channel_id):
            logger.info(
                "DepartmentResponderCog: rate-limited for %s (dept=%s)",
                getattr(message.channel, "name", "unknown"),
                dept["name"],
            )
            return

        logger.info(
            "DepartmentResponderCog: delegation detected in %s (dept=%s, message=%d, author=%s)",
            getattr(message.channel, "name", "unknown"),
            dept["name"],
            message.id,
            message.author.name,
        )

        self._last_session[parent_channel_id] = time.monotonic()
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
