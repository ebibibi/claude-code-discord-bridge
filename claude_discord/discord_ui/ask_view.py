"""Discord UI components for AskUserQuestion interactive prompts.

Design
------
AskView is a **persistent** view (timeout=None).  Persistent views survive bot
restarts: on_ready re-registers them via ``bot.add_view()``, so buttons in old
messages keep working rather than showing Discord's generic "Interaction Failed".

Answer routing uses :mod:`ask_bus` (an in-process asyncio.Queue per thread).
The waiting side (``_collect_ask_answers`` in _run_helper.py) calls
``ask_bus.register(thread_id)`` and awaits ``queue.get()`` with a 24-hour
timeout instead of the old 5-minute hard limit.
AskView callbacks call ``ask_bus.post_answer(thread_id, labels)``; if the
session is gone after a restart, post_answer returns False and the view shows
a clear "session ended" message instead of silently failing.

custom_id format:  ``ask_{thread_id}_{q_idx}_{slot}``
  - slot = 0..3 for regular buttons
  - slot = ``select`` for the Select menu
  - slot = ``other`` for the free-text button
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from .ask_bus import AskAnswerBus
from .ask_bus import ask_bus as _default_ask_bus

if TYPE_CHECKING:
    from ..claude.types import AskQuestion
    from ..database.ask_repo import PendingAskRepository

logger = logging.getLogger(__name__)

_RESTART_MSG = (
    "⚠️ The bot was restarted since this question was asked. "
    "The session is no longer active. Please send a new message to continue."
)


class AskView(discord.ui.View):
    """Renders buttons or a select menu for a single AskUserQuestion prompt.

    This is a **persistent** view — ``timeout=None``.  Register it with the
    bot via ``bot.add_view(view)`` so that button clicks still work after a
    bot restart (they'll receive a graceful "session ended" message).

    Answers are routed via :data:`ask_bus` rather than an internal Future,
    so the waiting coroutine (``_collect_ask_answers``) can use any timeout
    and ``view.stop()`` is always called on interaction.

    Usage::

        view = AskView(question, thread_id=thread.id, q_idx=0)
        bot.add_view(view)                 # register for restart recovery
        await thread.send(embed=..., view=view)
        # answer arrives via ask_bus.register(thread_id) → queue.get()
    """

    def __init__(
        self,
        question: AskQuestion,
        thread_id: int,
        q_idx: int,
        bus: AskAnswerBus | None = None,
        ask_repo: PendingAskRepository | None = None,
    ) -> None:
        super().__init__(timeout=None)  # persistent — survives bot restarts
        self._thread_id = thread_id
        self._bus = bus if bus is not None else _default_ask_bus
        self._ask_repo = ask_repo

        options = question.options
        use_select = question.multi_select or len(options) > 4

        if use_select and options:
            max_vals = len(options) if question.multi_select else 1
            select = discord.ui.Select(
                placeholder=question.header or "Choose an option…",
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
                custom_id=f"ask_{thread_id}_{q_idx}_select",
            )
            select.callback = self._select_callback
            self.add_item(select)
        elif options:
            for i, opt in enumerate(options[:4]):
                btn = discord.ui.Button(
                    label=opt.label[:80],
                    style=discord.ButtonStyle.primary,
                    custom_id=f"ask_{thread_id}_{q_idx}_{i}",
                    row=0,
                )
                btn.callback = _make_button_callback(self, opt.label)
                self.add_item(btn)

        other_btn = discord.ui.Button(
            label="✏️ Other",
            style=discord.ButtonStyle.secondary,
            custom_id=f"ask_{thread_id}_{q_idx}_other",
            row=1,
        )
        other_btn.callback = self._other_callback
        self.add_item(other_btn)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _deliver(self, interaction: discord.Interaction, values: list[str]) -> None:
        """Deliver *values* via the bus and update the Discord message.

        If the session is still alive (bus has a waiter), the interaction
        message is edited to show the selection and buttons are removed —
        giving clear visual confirmation before Claude resumes.

        If the session is gone (bot restarted), an ephemeral error message is
        sent and the stale DB entry is cleaned up.
        """
        delivered = self._bus.post_answer(self._thread_id, values)
        if delivered:
            label = ", ".join(values)
            await interaction.response.edit_message(
                content=f"-# ✅ **Selected:** {label}",
                embed=None,
                view=None,
            )
        else:
            # Bot was restarted — clean up stale DB entry and inform user.
            if self._ask_repo is not None:
                await self._ask_repo.delete(self._thread_id)
            await interaction.response.send_message(_RESTART_MSG, ephemeral=True)
        self.stop()

    async def _select_callback(self, interaction: discord.Interaction) -> None:
        values: list[str] = interaction.data.get("values", [])  # type: ignore[union-attr]
        await self._deliver(interaction, values)

    async def _other_callback(self, interaction: discord.Interaction) -> None:
        modal = AskModal(title="Your answer")
        await interaction.response.send_modal(modal)
        timed_out = await modal.wait()
        if not timed_out and modal.answer:
            delivered = self._bus.post_answer(self._thread_id, [modal.answer])
            if not delivered:
                if self._ask_repo is not None:
                    await self._ask_repo.delete(self._thread_id)
                logger.warning(
                    "AskView._other_callback: session gone for thread %d after restart",
                    self._thread_id,
                )
            self.stop()


class AskModal(discord.ui.Modal):
    """Modal for free-text input when the user selects 'Other'."""

    def __init__(self, title: str) -> None:
        super().__init__(title=title[:45])
        self.answer: str = ""
        self.text_input = discord.ui.TextInput(
            label="Your answer",
            placeholder="Type your answer here…",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.answer = self.text_input.value
        await interaction.response.defer()
        self.stop()


def _make_button_callback(view: AskView, label: str):
    """Factory that creates a button callback with *view* and *label* bound.

    Passing *view* explicitly (instead of capturing a Future) means:
    - ``view._deliver()`` is called, which routes via ask_bus and calls
      ``view.stop()`` — fixing the 300-second hang of the old design.
    - The restart-recovery path is handled uniformly with select/other.
    """

    async def callback(interaction: discord.Interaction) -> None:
        await view._deliver(interaction, [label])

    return callback
