"""Tests for LiveToolTimer — elapsed-time embed updater."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord

from claude_discord.claude.types import ToolCategory, ToolUseEvent
from claude_discord.discord_ui.tool_timer import LiveToolTimer


def _make_tool() -> ToolUseEvent:
    return ToolUseEvent(
        tool_id="tool-123",
        tool_name="Bash",
        tool_input={"command": "ls"},
        category=ToolCategory.COMMAND,
    )


class TestLiveToolTimerLoop:
    async def test_cancels_cleanly(self) -> None:
        """Cancelling the timer task should not raise — CancelledError is caught internally."""
        msg = MagicMock(spec=discord.Message)
        msg.edit = AsyncMock()
        timer = LiveToolTimer(msg, _make_tool())
        task = timer.start()
        await asyncio.sleep(0)  # let the initial edit fire
        task.cancel()
        await asyncio.sleep(0)  # let cancel propagate
        assert task.done()
        # CancelledError is caught inside _loop(), so the task has no stored exception
        assert task.exception() is None

    async def test_suppresses_http_exception_on_edit(self) -> None:
        """discord.HTTPException during edit should be swallowed, not stored as task exception."""
        msg = MagicMock(spec=discord.Message)
        response = MagicMock()
        response.status = 403
        msg.edit = AsyncMock(side_effect=discord.Forbidden(response, "Missing Permissions"))
        timer = LiveToolTimer(msg, _make_tool())
        task = timer.start()
        await asyncio.sleep(0)  # initial edit fires and raises Forbidden — should be suppressed
        task.cancel()
        await asyncio.sleep(0)
        assert task.done()
        assert task.exception() is None

    async def test_suppresses_server_disconnected_error(self) -> None:
        """ServerDisconnectedError (raised on bot shutdown) must be suppressed.

        Previously this caused an 'asyncio: Task exception was never retrieved'
        log error on every bot restart while a tool was in progress.
        ServerDisconnectedError is an aiohttp error — not a discord.HTTPException —
        so it was previously not caught by the suppress block.
        """
        msg = MagicMock(spec=discord.Message)
        msg.edit = AsyncMock(side_effect=aiohttp.ServerDisconnectedError("Server disconnected"))
        timer = LiveToolTimer(msg, _make_tool())
        task = timer.start()
        await asyncio.sleep(0)  # initial edit fires and raises ServerDisconnectedError
        task.cancel()
        await asyncio.sleep(0)
        assert task.done()
        # Must NOT store ServerDisconnectedError as the task exception
        assert task.exception() is None
