"""tests/test_alert_responder.py

Unit tests for AlertResponderCog.

All configuration is sourced from environment variables; this test module sets
ALERT_MONITOR_CHANNEL_ID before importing the Cog so module-level constants
are initialised with a known test value.
"""

from __future__ import annotations

import os

# Set required env vars before the module under test is imported, because
# ALERT_CHANNEL_ID and _ALERT_PATTERN are resolved at import time.
os.environ.setdefault("ALERT_MONITOR_CHANNEL_ID", "111111111111111111")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import discord  # noqa: E402
import pytest  # noqa: E402

from examples.ebibot.cogs.alert_responder import (  # noqa: E402
    _ALERT_PATTERN,
    ALERT_CHANNEL_ID,
    AlertResponderCog,
)

# Sanity-check: the env var we set above must have been picked up.
assert int(os.environ["ALERT_MONITOR_CHANNEL_ID"]) == ALERT_CHANNEL_ID

_TEST_CHANNEL_ID: int = ALERT_CHANNEL_ID  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Pattern tests
# ---------------------------------------------------------------------------


class TestAlertPattern:
    def test_warning_emoji_matches(self) -> None:
        assert _ALERT_PATTERN.search("[BlueSky] ⚠️ ch5: Gemini failed")

    def test_plain_message_does_not_match(self) -> None:
        assert not _ALERT_PATTERN.search("[BlueSky] ✅ posted successfully")

    def test_error_without_warning_emoji_does_not_match(self) -> None:
        assert not _ALERT_PATTERN.search("[Agent Pipeline] error: see logs")


# ---------------------------------------------------------------------------
# Discord mock helpers
# ---------------------------------------------------------------------------


def _make_text_channel(channel_id: int) -> MagicMock:
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    ch.create_thread = AsyncMock()
    return ch


def _make_message(
    content: str,
    channel_id: int = _TEST_CHANNEL_ID,
    is_bot: bool = False,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.id = 12345
    msg.author = MagicMock()
    msg.author.bot = is_bot
    channel = _make_text_channel(channel_id)
    msg.channel = channel
    mock_thread = AsyncMock(spec=discord.Thread)
    mock_thread.id = 99999
    mock_thread.send = AsyncMock()
    msg.create_thread = AsyncMock(return_value=mock_thread)
    return msg


def _make_bot(is_bot_author: bool = False) -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.user = MagicMock()
    bot.user.bot = is_bot_author
    return bot


def _make_cog(bot: MagicMock | None = None) -> AlertResponderCog:
    if bot is None:
        bot = _make_bot()
    runner = MagicMock()
    runner.clone = MagicMock(return_value=MagicMock())
    components = MagicMock()
    cog = AlertResponderCog(bot, runner, components)
    bot_user = MagicMock()
    cog.bot.user = bot_user
    return cog


# ---------------------------------------------------------------------------
# on_message — skip conditions
# ---------------------------------------------------------------------------


class TestOnMessageSkip:
    @pytest.mark.asyncio
    async def test_ignores_bot_own_message(self) -> None:
        """Bot's own messages are ignored."""
        cog = _make_cog()
        msg = _make_message("⚠️ test")
        msg.author = cog.bot.user  # same object → identity check passes

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_wrong_channel(self) -> None:
        """Messages in other channels are ignored."""
        cog = _make_cog()
        msg = _make_message("⚠️ test", channel_id=999999)

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_alert_message(self) -> None:
        """Messages without the alert pattern are ignored."""
        cog = _make_cog()
        msg = _make_message("✅ posted: https://bsky.app/...")

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_duplicate_message(self) -> None:
        """A message already being investigated is not queued again."""
        cog = _make_cog()
        msg = _make_message("⚠️ test")
        cog._investigating.add(msg.id)

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()


# ---------------------------------------------------------------------------
# on_message — detection conditions
# ---------------------------------------------------------------------------


class TestOnMessageDetect:
    @pytest.mark.asyncio
    async def test_triggers_investigation_for_alert(self) -> None:
        """A matching message triggers investigation."""
        cog = _make_cog()
        msg = _make_message("[Service] ⚠️ Gemini timed out")

        with patch.object(cog, "_start_investigation", new_callable=AsyncMock) as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_removes_message_from_investigating_after_completion(self) -> None:
        """Message ID is removed from _investigating after the investigation finishes."""
        cog = _make_cog()
        msg = _make_message("⚠️ test")

        with patch.object(cog, "_start_investigation", new_callable=AsyncMock):
            await cog.on_message(msg)

        assert msg.id not in cog._investigating

    @pytest.mark.asyncio
    async def test_removes_message_from_investigating_on_error(self) -> None:
        """Message ID is cleaned up even if investigation raises an exception."""
        cog = _make_cog()
        msg = _make_message("⚠️ test")

        with patch.object(
            cog,
            "_start_investigation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("test error"),
        ):
            await cog.on_message(msg)  # exception is swallowed

        assert msg.id not in cog._investigating


# ---------------------------------------------------------------------------
# _start_investigation — thread creation
# ---------------------------------------------------------------------------


class TestStartInvestigation:
    @pytest.mark.asyncio
    async def test_creates_thread_on_alert_message(self) -> None:
        """A thread is created on the alert message."""
        cog = _make_cog()
        msg = _make_message("[Service] ⚠️ connection timeout")

        with patch(
            "examples.ebibot.cogs.alert_responder.run_claude_with_config", new_callable=AsyncMock
        ):
            await cog._start_investigation(msg)

        msg.create_thread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_runner_is_none(self) -> None:
        """No thread is created when runner is None."""
        cog = _make_cog()
        cog.runner = None
        msg = _make_message("⚠️ test")

        with patch(
            "examples.ebibot.cogs.alert_responder.run_claude_with_config", new_callable=AsyncMock
        ) as mock_run:
            await cog._start_investigation(msg)

        mock_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_alert_text_included_in_prompt(self) -> None:
        """The alert message content is embedded in the prompt."""
        cog = _make_cog()
        alert_text = "[Service] ⚠️ connection refused"
        msg = _make_message(alert_text)

        captured_config = None

        async def capture(config):  # type: ignore[no-untyped-def]
            nonlocal captured_config
            captured_config = config

        with patch(
            "examples.ebibot.cogs.alert_responder.run_claude_with_config", side_effect=capture
        ):
            await cog._start_investigation(msg)

        assert captured_config is not None
        assert alert_text in captured_config.prompt
