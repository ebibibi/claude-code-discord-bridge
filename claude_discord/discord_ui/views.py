"""Discord UI Views for interactive session controls."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import discord

from ..claude.rewind import TurnEntry, truncate_jsonl_at_line
from ..claude.runner import ClaudeRunner
from .embeds import COLOR_SUCCESS, stopped_embed, tool_result_embed, tool_result_preview_embed

if TYPE_CHECKING:
    from ..database.repository import SessionRecord
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

    @discord.ui.button(label="Expand ▼", style=discord.ButtonStyle.secondary)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Toggle between collapsed (preview) and expanded (full) output."""
        self._expanded = not self._expanded
        if self._expanded:
            button.label = "Collapse ▲"
            embed = tool_result_embed(self._tool_title, self._full_content)
        else:
            button.label = "Expand ▼"
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


class RewindSelectView(discord.ui.View):
    """Select menu for choosing which conversation turn to rewind to.

    Shows a list of past user messages (oldest to newest).  The user picks
    one; everything from that message onward is removed from the session JSONL
    so that ``--resume session_id`` resumes from just before that message.

    The active runner is stopped before truncation so it cannot write new JSONL
    entries that would be discarded.  The DB session record is intentionally
    **not** deleted — only the JSONL is trimmed — so the next message in the
    thread uses ``--resume`` and picks up from the rewound state.
    """

    def __init__(
        self,
        turns: list[TurnEntry],
        jsonl_path: Path,
        active_runners: dict,
        thread_id: int,
    ) -> None:
        super().__init__(timeout=60)
        self._turns = turns
        self._jsonl_path = jsonl_path
        self._active_runners = active_runners
        self._thread_id = thread_id

        options = [
            discord.SelectOption(
                label=f"↩ {turn.text[:90]}",
                value=str(i),
                description=(turn.timestamp[:10] if turn.timestamp else None),
            )
            for i, turn in enumerate(turns)
        ]

        select = discord.ui.Select(
            placeholder="Select the turn to rewind before...",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

        cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        data = cast(dict[str, Any], interaction.data)
        idx = int(data["values"][0])
        turn = self._turns[idx]

        # Stop any active runner first so it cannot append new JSONL lines.
        runner = self._active_runners.pop(self._thread_id, None)
        if runner is not None:
            with contextlib.suppress(Exception):
                await runner.kill()

        success = truncate_jsonl_at_line(self._jsonl_path, turn.line_index)

        if success:
            preview = turn.text[:60]
            msg = (
                f"⏪ **Rewound** — removed everything from: _{preview}_\n"
                "Conversation history has been truncated. "
                "Send a new message to continue from the rewound state."
            )
        else:
            msg = (
                "⚠️ **Rewind failed** — could not truncate conversation history. "
                "The session was not modified."
            )

        await interaction.response.edit_message(content=msg, view=None)
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Rewind cancelled.", view=None)
        self.stop()

    async def on_timeout(self) -> None:
        """No-op: the message remains but the view becomes inactive."""


_ORIGIN_ICON = {
    "discord": "\U0001f4ac",  # 💬
    "cli": "\U0001f5a5\ufe0f",  # 🖥️
}


class ResumeSelectView(discord.ui.View):
    """Select menu for choosing a session to resume in a new thread.

    Shows a list of recent sessions with their summary and origin.
    When the user picks one, a new thread is created and the selected
    session is resumed via ``--resume``.
    """

    def __init__(
        self,
        records: list[SessionRecord],
        bot: Any,
    ) -> None:
        super().__init__(timeout=60)
        self._records = records
        self._bot = bot

        options = [
            discord.SelectOption(
                label=self._build_label(record),
                value=str(i),
                description=self._build_description(record),
            )
            for i, record in enumerate(records[:25])
        ]

        select = discord.ui.Select(
            placeholder="Select a session to resume...",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    @staticmethod
    def _build_label(record: SessionRecord) -> str:
        icon = _ORIGIN_ICON.get(record.origin, "")
        summary = record.summary or "(no summary)"
        prefix = f"{icon} " if icon else ""
        return f"{prefix}{summary}"[:100]

    @staticmethod
    def _build_description(record: SessionRecord) -> str | None:
        parts: list[str] = []
        if record.working_dir:
            parts.append(record.working_dir)
        parts.append(record.last_used_at[:16])
        desc = " | ".join(parts)
        return desc[:100] if desc else None

    async def _on_select(self, interaction: discord.Interaction) -> None:
        data = cast(dict[str, Any], interaction.data)
        idx = int(data["values"][0])
        record = self._records[idx]

        chat_cog = self._bot.get_cog("ClaudeChatCog")
        if chat_cog is None:
            await interaction.response.edit_message(
                content="\u274c ClaudeChatCog is not loaded — cannot resume.",
                view=None,
            )
            self.stop()
            return

        channel = self._bot.get_channel(self._bot.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.edit_message(
                content="\u274c Channel not found — cannot create thread.",
                view=None,
            )
            self.stop()
            return

        await interaction.response.edit_message(
            content=f"\U0001f504 Resuming session: _{record.summary or record.session_id[:8]}_...",
            view=None,
        )

        thread_name = f"\u25b6 {record.summary or 'Resumed session'}"[:100]
        await chat_cog.spawn_session(
            channel=channel,
            prompt="Resuming previous session. Continue from where we left off.",
            thread_name=thread_name,
            session_id=record.session_id,
        )

        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(
                "\u2705 Resumed in a new thread!",
                ephemeral=True,
            )
        self.stop()

    async def on_timeout(self) -> None:
        """No-op: the message remains but the view becomes inactive."""
