"""Discord UI Views for interactive session controls."""

from __future__ import annotations

import contextlib
import logging

import discord

from ..claude.runner import ClaudeRunner
from .embeds import stopped_embed

logger = logging.getLogger(__name__)


class StopView(discord.ui.View):
    """A ⏹ Stop button attached to the session status message.

    Clicking it sends SIGINT to the active Claude runner (graceful interrupt,
    like pressing Escape in Claude Code) and posts a stopped_embed.

    After the session ends — either via the button or naturally — call
    ``disable()`` to deactivate the button on the status message.

    Call ``bump(thread)`` after each major Discord message to keep the Stop
    button at the bottom of the thread (most recently visible position).
    """

    def __init__(self, runner: ClaudeRunner) -> None:
        super().__init__(timeout=None)
        self._runner = runner
        self._stopped = False
        self._message: discord.Message | None = None

    def set_message(self, message: discord.Message) -> None:
        """Store the message this view is attached to."""
        self._message = message

    async def bump(self, thread: discord.Thread) -> None:
        """Re-post the Stop button as the latest message in the thread.

        Deletes the old stop message and sends a new one at the bottom so the
        button stays accessible as Claude sends new messages above it.
        No-op if the session has already been stopped.
        """
        if self._stopped:
            return

        old_message = self._message
        with contextlib.suppress(discord.HTTPException):
            new_message = await thread.send("-# ⏺ Session running", view=self)
            self._message = new_message

        if old_message:
            with contextlib.suppress(discord.HTTPException):
                await old_message.delete()

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger)
    async def stop_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Interrupt the active Claude session."""
        if self._stopped:
            await interaction.response.defer()
            return

        self._stopped = True
        button.disabled = True
        self.stop()

        await interaction.response.edit_message(view=self)
        await self._runner.interrupt()

        with contextlib.suppress(Exception):
            await interaction.followup.send(embed=stopped_embed())

    async def disable(self, message: discord.Message | None = None) -> None:
        """Disable the button after the session ends naturally.

        Uses the stored message reference if ``message`` is not provided.
        No-op if the stop button was already clicked.
        """
        if self._stopped:
            return

        target = message or self._message
        self._stopped = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        self.stop()

        if target:
            with contextlib.suppress(discord.HTTPException):
                await target.edit(view=self)
