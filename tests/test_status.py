"""Unit tests for StatusManager stall notification feature."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.claude.types import ToolCategory
from claude_discord.discord_ui.status import (
    STALL_HARD_SECONDS,
    StatusManager,
)


def _make_message() -> MagicMock:
    """Create a mock Discord message with guild.me for reactions."""
    msg = MagicMock()
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.guild = MagicMock()
    msg.guild.me = MagicMock()
    return msg


class TestHardStallCallback:
    """Tests for the on_hard_stall callback feature."""

    @pytest.mark.asyncio
    async def test_callback_fires_on_hard_stall(self) -> None:
        callback = AsyncMock()
        msg = _make_message()
        sm = StatusManager(msg, on_hard_stall=callback)
        await sm.set_thinking()
        loop = asyncio.get_running_loop()
        sm._last_activity = loop.time() - STALL_HARD_SECONDS - 1
        await asyncio.sleep(2.5)
        callback.assert_awaited_once()
        await sm.cleanup()

    @pytest.mark.asyncio
    async def test_callback_fires_only_once_per_stall(self) -> None:
        callback = AsyncMock()
        msg = _make_message()
        sm = StatusManager(msg, on_hard_stall=callback)
        await sm.set_thinking()
        loop = asyncio.get_running_loop()
        sm._last_activity = loop.time() - STALL_HARD_SECONDS - 1
        await asyncio.sleep(5)
        callback.assert_awaited_once()
        await sm.cleanup()

    @pytest.mark.asyncio
    async def test_callback_resets_after_activity(self) -> None:
        callback = AsyncMock()
        msg = _make_message()
        sm = StatusManager(msg, on_hard_stall=callback)
        await sm.set_thinking()
        loop = asyncio.get_running_loop()
        sm._last_activity = loop.time() - STALL_HARD_SECONDS - 1
        await asyncio.sleep(2.5)
        assert callback.await_count == 1
        await sm.set_tool(ToolCategory.READ)
        sm._last_activity = loop.time() - STALL_HARD_SECONDS - 1
        await asyncio.sleep(2.5)
        assert callback.await_count == 2
        await sm.cleanup()

    @pytest.mark.asyncio
    async def test_no_callback_when_not_provided(self) -> None:
        msg = _make_message()
        sm = StatusManager(msg)
        await sm.set_thinking()
        loop = asyncio.get_running_loop()
        sm._last_activity = loop.time() - STALL_HARD_SECONDS - 1
        await asyncio.sleep(2.5)
        await sm.cleanup()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash_monitor(self) -> None:
        callback = AsyncMock(side_effect=Exception("Discord API error"))
        msg = _make_message()
        sm = StatusManager(msg, on_hard_stall=callback)
        await sm.set_thinking()
        loop = asyncio.get_running_loop()
        sm._last_activity = loop.time() - STALL_HARD_SECONDS - 1
        await asyncio.sleep(2.5)
        callback.assert_awaited_once()
        assert sm._stall_task is not None
        assert not sm._stall_task.done()
        await sm.cleanup()
