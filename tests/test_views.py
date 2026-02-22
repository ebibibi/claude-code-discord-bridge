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

    @pytest.mark.asyncio
    async def test_disable_uses_stored_message(self) -> None:
        """disable() without args uses the message stored via set_message()."""
        runner = _make_runner()
        view = StopView(runner)
        msg = _make_message()
        view.set_message(msg)

        await view.disable()

        msg.edit.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_no_message_no_crash(self) -> None:
        """disable() without args and no stored message does not raise."""
        runner = _make_runner()
        view = StopView(runner)

        await view.disable()  # should not raise


def _make_thread() -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.send = AsyncMock(return_value=_make_message())
    return thread


class TestStopViewBump:
    @pytest.mark.asyncio
    async def test_bump_sends_new_message(self) -> None:
        """bump() sends a new message to the thread."""
        runner = _make_runner()
        view = StopView(runner)
        thread = _make_thread()

        await view.bump(thread)

        thread.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_bump_deletes_old_message(self) -> None:
        """bump() deletes the old stop message after sending the new one."""
        runner = _make_runner()
        view = StopView(runner)
        thread = _make_thread()
        old_msg = _make_message()
        old_msg.delete = AsyncMock()
        view.set_message(old_msg)

        await view.bump(thread)

        old_msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_bump_updates_stored_message(self) -> None:
        """bump() updates the internal message reference to the new message."""
        runner = _make_runner()
        view = StopView(runner)
        thread = _make_thread()
        new_msg = _make_message()
        thread.send = AsyncMock(return_value=new_msg)

        await view.bump(thread)

        assert view._message is new_msg

    @pytest.mark.asyncio
    async def test_bump_noop_when_stopped(self) -> None:
        """bump() does nothing after the session has been stopped."""
        runner = _make_runner()
        view = StopView(runner)
        thread = _make_thread()
        await _click(view, _make_interaction())  # stop the session

        await view.bump(thread)

        thread.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_bump_suppresses_http_exception(self) -> None:
        """bump() swallows discord.HTTPException from send silently."""
        runner = _make_runner()
        view = StopView(runner)
        thread = _make_thread()
        thread.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "rate limited"))

        await view.bump(thread)  # should not raise
