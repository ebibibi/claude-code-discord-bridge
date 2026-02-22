"""Emoji reaction status manager.

Inspired by OpenClaw's approach: use message reactions to show agent status.
Debounced to avoid Discord API rate limits.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

import discord

from ..claude.types import ToolCategory

logger = logging.getLogger(__name__)

# Status emoji mapping
EMOJI_THINKING = "\U0001f9e0"  # 🧠
EMOJI_TOOL = "\U0001f6e0\ufe0f"  # 🛠️
EMOJI_CODING = "\U0001f4bb"  # 💻
EMOJI_WEB = "\U0001f310"  # 🌐
EMOJI_DONE = "\u2705"  # ✅
EMOJI_ERROR = "\u274c"  # ❌
EMOJI_STALL_SOFT = "\u23f3"  # ⏳
EMOJI_STALL_HARD = "\u26a0\ufe0f"  # ⚠️

# Tool category to emoji
CATEGORY_EMOJI: dict[ToolCategory, str] = {
    ToolCategory.READ: EMOJI_TOOL,
    ToolCategory.EDIT: EMOJI_CODING,
    ToolCategory.COMMAND: EMOJI_CODING,
    ToolCategory.WEB: EMOJI_WEB,
    ToolCategory.THINK: EMOJI_THINKING,
    ToolCategory.OTHER: EMOJI_TOOL,
}

DEBOUNCE_MS = 700
STALL_SOFT_SECONDS = 10
STALL_HARD_SECONDS = 30


class StatusManager:
    """Manages emoji reactions on a Discord message to show Claude's status.

    Only one status emoji is shown at a time. Transitions are debounced
    to avoid hitting Discord's rate limits.
    """

    def __init__(
        self,
        message: discord.Message,
        on_hard_stall: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._message = message
        self._current_emoji: str | None = None
        self._target_emoji: str | None = None
        self._debounce_task: asyncio.Task | None = None
        self._stall_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_activity = asyncio.get_running_loop().time()
        self._on_hard_stall = on_hard_stall
        self._hard_stall_notified = False

    async def set_thinking(self) -> None:
        """Set status to thinking."""
        await self._set_status(EMOJI_THINKING)
        self._start_stall_timer()

    async def set_tool(self, category: ToolCategory) -> None:
        """Set status based on tool category."""
        emoji = CATEGORY_EMOJI.get(category, EMOJI_TOOL)
        await self._set_status(emoji)
        self._reset_stall_timer()

    async def set_done(self) -> None:
        """Set status to done."""
        self._cancel_stall_timer()
        await self._set_status(EMOJI_DONE)
        # Hold done emoji briefly, then clean up
        await asyncio.sleep(1.5)
        await self.cleanup()

    async def set_error(self) -> None:
        """Set status to error."""
        self._cancel_stall_timer()
        await self._set_status(EMOJI_ERROR)
        # Hold error emoji longer
        await asyncio.sleep(2.5)
        await self.cleanup()

    async def cleanup(self) -> None:
        """Remove all status reactions."""
        self._cancel_stall_timer()
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._current_emoji:
            with contextlib.suppress(discord.HTTPException, AttributeError):
                guild = self._message.guild
                if guild:
                    await self._message.remove_reaction(self._current_emoji, guild.me)
            self._current_emoji = None

    async def _set_status(self, emoji: str) -> None:
        """Set the target emoji with debouncing."""
        self._target_emoji = emoji

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        self._debounce_task = asyncio.create_task(self._apply_debounced())

    async def _apply_debounced(self) -> None:
        """Apply the status change after debounce delay."""
        await asyncio.sleep(DEBOUNCE_MS / 1000)

        async with self._lock:
            if self._target_emoji == self._current_emoji:
                return

            # Remove old emoji
            if self._current_emoji:
                with contextlib.suppress(discord.HTTPException, AttributeError):
                    guild = self._message.guild
                    if guild:
                        await self._message.remove_reaction(self._current_emoji, guild.me)

            # Add new emoji
            if self._target_emoji:
                with contextlib.suppress(discord.HTTPException):
                    await self._message.add_reaction(self._target_emoji)

            self._current_emoji = self._target_emoji

    def _start_stall_timer(self) -> None:
        """Start the stall detection timer."""
        self._cancel_stall_timer()
        self._last_activity = asyncio.get_running_loop().time()
        self._stall_task = asyncio.create_task(self._stall_monitor())

    def _reset_stall_timer(self) -> None:
        """Reset the stall timer (activity detected)."""
        self._last_activity = asyncio.get_running_loop().time()
        self._hard_stall_notified = False

    def _cancel_stall_timer(self) -> None:
        """Cancel the stall timer."""
        if self._stall_task and not self._stall_task.done():
            self._stall_task.cancel()

    async def _stall_monitor(self) -> None:
        """Monitor for stall conditions and update emoji accordingly."""
        soft_warned = False
        while True:
            await asyncio.sleep(2)
            elapsed = asyncio.get_running_loop().time() - self._last_activity

            if elapsed >= STALL_HARD_SECONDS and self._current_emoji != EMOJI_STALL_HARD:
                await self._set_status(EMOJI_STALL_HARD)
                if self._on_hard_stall and not self._hard_stall_notified:
                    self._hard_stall_notified = True
                    with contextlib.suppress(Exception):
                        await self._on_hard_stall()
            elif (
                elapsed >= STALL_SOFT_SECONDS
                and not soft_warned
                and self._current_emoji != EMOJI_STALL_HARD
            ):
                await self._set_status(EMOJI_STALL_SOFT)
                soft_warned = True
