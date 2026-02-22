"""Tests for CoordinationService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.coordination.service import CoordinationService


def _make_thread(name: str = "Test Thread") -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.name = name
    return thread


def _make_channel() -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


def _make_bot(channel: MagicMock | None = None) -> MagicMock:
    bot = MagicMock(spec=discord.Client)
    bot.get_channel = MagicMock(return_value=channel)
    return bot


class TestCoordinationServiceEnabled:
    def test_enabled_when_channel_id_set(self) -> None:
        svc = CoordinationService(_make_bot(), channel_id=1234)
        assert svc.enabled is True

    def test_disabled_when_channel_id_none(self) -> None:
        svc = CoordinationService(_make_bot(), channel_id=None)
        assert svc.enabled is False


class TestCoordinationServiceNoOp:
    """When no channel is configured all methods are no-ops."""

    @pytest.mark.asyncio
    async def test_post_session_end_noop(self) -> None:
        bot = _make_bot()
        svc = CoordinationService(bot, channel_id=None)
        await svc.post_session_end(_make_thread())
        bot.get_channel.assert_not_called()


class TestCoordinationServicePosts:
    """When a channel is configured, posts are sent."""

    @pytest.mark.asyncio
    async def test_post_session_end_sends_message(self) -> None:
        channel = _make_channel()
        bot = _make_bot(channel)
        svc = CoordinationService(bot, channel_id=9999)

        thread = _make_thread("Issue #42")
        await svc.post_session_end(thread)

        channel.send.assert_called_once()
        sent = channel.send.call_args[0][0]
        assert "Issue #42" in sent


class TestCoordinationServiceChannelNotFound:
    """When get_channel returns None (not in cache), methods are silent no-ops."""

    @pytest.mark.asyncio
    async def test_end_no_channel_in_cache(self) -> None:
        bot = _make_bot(channel=None)
        svc = CoordinationService(bot, channel_id=9999)
        await svc.post_session_end(_make_thread())


class TestCoordinationServiceHTTPError:
    """HTTP errors from Discord are swallowed so they never crash the bot."""

    @pytest.mark.asyncio
    async def test_http_error_on_end_is_swallowed(self) -> None:
        channel = _make_channel()
        http_response = MagicMock()
        http_response.status = 500
        http_response.reason = "Internal Server Error"
        channel.send.side_effect = discord.HTTPException(http_response, "error")

        bot = _make_bot(channel)
        svc = CoordinationService(bot, channel_id=9999)

        await svc.post_session_end(_make_thread())
