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
    ``disable(message)`` to deactivate the button on the status message.
    """

    def __init__(self, runner: ClaudeRunner) -> None:
        super().__init__(timeout=None)
        self._runner = runner
        self._stopped = False

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

    async def disable(self, message: discord.Message) -> None:
        """Disable the button after the session ends naturally.

        No-op if the stop button was already clicked.
        """
        if self._stopped:
            return

        self._stopped = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        self.stop()

        with contextlib.suppress(discord.HTTPException):
            await message.edit(view=self)
