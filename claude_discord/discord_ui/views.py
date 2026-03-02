"""Discord UI Views for interactive session controls."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import discord

from ..claude.runner import ClaudeRunner
from .embeds import COLOR_SUCCESS, stopped_embed, tool_result_embed, tool_result_preview_embed

if TYPE_CHECKING:
    from ..database.settings_repo import SettingsRepository

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

    def update_runner(self, runner: ClaudeRunner) -> None:
        """Replace the runner reference with the one that owns the live subprocess.

        ``run_claude_with_config`` may clone the runner to inject an
        ``--append-system-prompt`` (lounge context, concurrency notice).
        The subprocess lives in that clone, not in the original runner passed
        to the constructor.  Call this immediately after the clone is created
        so that the Stop button sends SIGINT to the right process.
        """
        self._runner = runner

    async def bump(self, thread: discord.Thread | discord.TextChannel) -> None:
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

        with contextlib.suppress(discord.HTTPException):
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


class ToolResultView(discord.ui.View):
    """▼/▲ toggle button that collapses or expands a tool result embed.

    Posted alongside the tool result when the output exceeds the preview
    threshold, so the thread stays compact by default.
    """

    def __init__(self, tool_title: str, full_content: str) -> None:
        super().__init__(timeout=3600)
        self._tool_title = tool_title
        self._full_content = full_content
        self._expanded = False

    @discord.ui.button(label="展開 ▼", style=discord.ButtonStyle.secondary)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Toggle between collapsed (preview) and expanded (full) output."""
        self._expanded = not self._expanded
        if self._expanded:
            button.label = "折りたたむ ▲"
            embed = tool_result_embed(self._tool_title, self._full_content)
        else:
            button.label = "展開 ▼"
            embed = tool_result_preview_embed(self._tool_title, self._full_content)
        await interaction.response.edit_message(embed=embed, view=self)


class ToolSelectView(discord.ui.View):
    """Multi-select menu for choosing which Claude tools are allowed.

    Displays all known tools as options. Tools that are currently enabled
    are pre-selected.  On submit, the selection is persisted to settings_repo.
    """

    def __init__(
        self,
        known_tools: list[str],
        current_tools: list[str] | None,
        settings_repo: SettingsRepository,
        setting_key: str,
    ) -> None:
        super().__init__(timeout=120)
        self._settings_repo = settings_repo
        self._setting_key = setting_key

        current_set = set(current_tools) if current_tools else set()

        options = [
            discord.SelectOption(
                label=tool,
                value=tool,
                default=tool in current_set,
            )
            for tool in known_tools
        ]

        self._select = discord.ui.Select(
            placeholder="Select tools to allow...",
            min_values=0,
            max_values=len(known_tools),
            options=options,
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        """Persist the selected tools to settings_repo."""
        selected = sorted(self._select.values)
        if selected:
            await self._settings_repo.set(self._setting_key, ",".join(selected))
            desc = "Allowed tools updated:\n" + ", ".join(f"`{t}`" for t in selected)
        else:
            await self._settings_repo.delete(self._setting_key)
            desc = "All tool restrictions removed — all tools are now allowed."

        embed = discord.Embed(title="✅ Tools Updated", description=desc, color=COLOR_SUCCESS)
        await interaction.response.edit_message(content=None, embed=embed, view=None)
        self.stop()
