"""Discord UI components for AskUserQuestion interactive prompts.

When Claude calls AskUserQuestion, this module renders the options as
Discord Buttons (for 2-4 options) or a Select Menu (for multi-select or
more than 4 options), and waits for the user to respond.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ..claude.types import AskQuestion

logger = logging.getLogger(__name__)

# How long to wait for user response before giving up (seconds)
ASK_TIMEOUT = 300


class AskView(discord.ui.View):
    """Renders buttons or a select menu for a single AskUserQuestion prompt.

    Usage::

        view = AskView(question)
        await thread.send(embed=ask_embed(...), view=view)
        selected = await view.wait_for_answer()
        # selected is a list of label strings, or [] on timeout
    """

    def __init__(self, question: AskQuestion) -> None:
        super().__init__(timeout=ASK_TIMEOUT)
        self._future: asyncio.Future[list[str]] = asyncio.get_event_loop().create_future()

        options = question.options

        use_select = question.multi_select or len(options) > 4

        if use_select and options:
            max_vals = len(options) if question.multi_select else 1
            select = discord.ui.Select(
                placeholder=question.header or "Choose an option...",
                min_values=1,
                max_values=min(max_vals, 25),
                options=[
                    discord.SelectOption(
                        label=opt.label[:100],
                        description=opt.description[:100] if opt.description else None,
                        value=opt.label[:100],
                    )
                    for opt in options[:25]
                ],
            )
            select.callback = self._select_callback
            self.add_item(select)
        elif options:
            # Buttons: up to 4 choices on row 0
            for i, opt in enumerate(options[:4]):
                btn = discord.ui.Button(
                    label=opt.label[:80],
                    style=discord.ButtonStyle.primary,
                    custom_id=f"ask_opt_{i}",
                    row=0,
                )
                btn.callback = _make_button_callback(self._future, opt.label)
                self.add_item(btn)

        # "Other / free text" button always available on row 1
        other_btn = discord.ui.Button(
            label="✏️ Other",
            style=discord.ButtonStyle.secondary,
            custom_id="ask_other",
            row=1,
        )
        other_btn.callback = self._other_callback
        self.add_item(other_btn)

    async def wait_for_answer(self) -> list[str]:
        """Wait for the user to interact. Returns selected labels, or [] on timeout."""
        await self.wait()
        if self._future.done():
            return self._future.result()
        return []

    async def on_timeout(self) -> None:
        if not self._future.done():
            self._future.set_result([])

    async def _select_callback(self, interaction: discord.Interaction) -> None:
        values: list[str] = interaction.data.get("values", [])  # type: ignore[union-attr]
        await interaction.response.defer()
        _resolve(self._future, values)
        self.stop()

    async def _other_callback(self, interaction: discord.Interaction) -> None:
        modal = AskModal(title="Your answer")
        await interaction.response.send_modal(modal)
        timed_out = await modal.wait()
        if not timed_out and modal.answer:
            _resolve(self._future, [modal.answer])
            self.stop()


class AskModal(discord.ui.Modal):
    """Modal for free-text input when the user selects 'Other'."""

    def __init__(self, title: str) -> None:
        super().__init__(title=title[:45])
        self.answer: str = ""
        self.text_input = discord.ui.TextInput(
            label="Your answer",
            placeholder="Type your answer here...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.answer = self.text_input.value
        await interaction.response.defer()
        self.stop()


def _make_button_callback(future: asyncio.Future[list[str]], label: str):
    """Factory that creates a button callback capturing `label` by value.

    Without this factory, all buttons in a loop would close over the same
    `label` variable (the last value in the loop).
    """

    async def callback(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        _resolve(future, [label])

    return callback


def _resolve(future: asyncio.Future[list[str]], value: list[str]) -> None:
    """Set the future result only if not already resolved."""
    if not future.done():
        future.set_result(value)
