"""Live tool timer for Discord embeds.

Periodically edits a Discord embed to show elapsed execution time for
long-running Claude Code tool invocations (e.g. Bash commands, web fetches).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import discord

from ..claude.types import ToolUseEvent
from .embeds import tool_use_embed

logger = logging.getLogger(__name__)

# How often to update in-progress tool embeds with elapsed time (seconds).
# Gives users visibility into long-running commands (builds, auth flows, etc.).
TOOL_TIMER_INTERVAL = 10


class LiveToolTimer:
    """Periodically edits a Discord embed to show elapsed execution time.

    Started when a tool_use event is received; cancelled when the corresponding
    tool_result arrives. For commands that finish quickly (<TOOL_TIMER_INTERVAL s)
    the timer fires zero times, so there is no overhead for fast tools.

    This provides basic visibility into long-running operations — the user can
    see "🔧 Running: az login... (10s)" ticking up rather than a frozen embed.
    Note: intermediate stdout from Bash is not exposed by the stream-json
    protocol, so only elapsed time (not actual output) is available here.
    """

    def __init__(self, msg: discord.Message, tool: ToolUseEvent) -> None:
        self._msg = msg
        self._tool = tool
        self._start = time.monotonic()

    def start(self) -> asyncio.Task[None]:
        """Schedule the timer loop and return the Task so callers can cancel it."""
        return asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(TOOL_TIMER_INTERVAL)
                elapsed = int(time.monotonic() - self._start)
                with contextlib.suppress(discord.HTTPException):
                    await self._msg.edit(
                        embed=tool_use_embed(self._tool, in_progress=True, elapsed_s=elapsed)
                    )
        except asyncio.CancelledError:
            pass
