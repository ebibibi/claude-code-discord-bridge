"""Tests for discord_ui/views.py — StopView."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.discord_ui.views import StopView


def _make_runner() -> MagicMock:
    runner = MagicMock()
    runner.interrupt = AsyncMock()
    return runner


def _make_interaction() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_message() -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.edit = AsyncMock()
    return msg


async def _click(view: StopView, interaction: MagicMock) -> None:
    """Simulate a button click by invoking the inner callback directly.

    @discord.ui.button wraps the method in a _ViewCallback whose inner
    .callback attribute is the original function.
    """
    btn = view.stop_button
    await btn.callback.callback(view, interaction, btn)


class TestStopViewButtonClick:
    @pytest.mark.asyncio
    async def test_click_calls_runner_interrupt(self) -> None:
        """Clicking ⏹ Stop calls runner.interrupt()."""
        runner = _make_runner()
        view = StopView(runner)

        await _click(view, _make_interaction())

        runner.interrupt.assert_called_once()

    @pytest.mark.asyncio
    async def test_click_disables_button(self) -> None:
        """Clicking ⏹ Stop disables the button."""
        runner = _make_runner()
        view = StopView(runner)
        btn = view.stop_button

        await _click(view, _make_interaction())

        assert btn.disabled is True

    @pytest.mark.asyncio
    async def test_click_edits_message(self) -> None:
        """Clicking ⏹ Stop edits the interaction message to show the disabled button."""
        runner = _make_runner()
        view = StopView(runner)
        interaction = _make_interaction()

        await _click(view, interaction)

        interaction.response.edit_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_click_sends_stopped_embed_via_followup(self) -> None:
        """Clicking ⏹ Stop sends stopped_embed via followup."""
        runner = _make_runner()
        view = StopView(runner)
        interaction = _make_interaction()

        await _click(view, interaction)

        interaction.followup.send.assert_called_once()
        embed = interaction.followup.send.call_args.kwargs.get("embed")
        assert embed is not None
        assert "stopped" in embed.title.lower()

    @pytest.mark.asyncio
    async def test_double_click_is_noop(self) -> None:
        """A second click after the first is ignored (idempotent)."""
        runner = _make_runner()
        view = StopView(runner)
        interaction = _make_interaction()

        await _click(view, interaction)
        runner.interrupt.reset_mock()
        interaction.response.edit_message.reset_mock()

        await _click(view, interaction)

        runner.interrupt.assert_not_called()
        interaction.response.defer.assert_called_once()


class TestStopViewDisable:
    @pytest.mark.asyncio
    async def test_disable_edits_message(self) -> None:
        """disable() edits the status message to show the deactivated button."""
        runner = _make_runner()
        view = StopView(runner)

        await view.disable(_make_message())

        _make_message()  # unused; just ensuring no exception

    @pytest.mark.asyncio
    async def test_disable_edits_message_for_real(self) -> None:
        """disable() calls message.edit to reflect the disabled button."""
        runner = _make_runner()
        view = StopView(runner)
        msg = _make_message()

        await view.disable(msg)

        msg.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_after_click_is_noop(self) -> None:
        """disable() after the stop button was clicked should not edit the message again."""
        runner = _make_runner()
        view = StopView(runner)
        msg = _make_message()

        await _click(view, _make_interaction())
        await view.disable(msg)

        msg.edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_disable_suppresses_http_exception(self) -> None:
        """disable() swallows discord.HTTPException silently."""
        runner = _make_runner()
        view = StopView(runner)
        msg = _make_message()
        msg.edit = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "rate limited"))

        await view.disable(msg)  # should not raise
