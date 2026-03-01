"""Thread status dashboard — live embed showing all active session states.

Posts and maintains a pinned embed in the main channel that shows which
threads are processing automatically vs. waiting for user input.
When a thread transitions to WAITING_INPUT, the bot mentions the owner
so Discord's notification system surfaces the request immediately.

Issue: https://github.com/ebibibi/claude-code-discord-bridge/issues/67
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

import discord

logger = logging.getLogger(__name__)

# Embed colours
_COLOR_PROCESSING = 0x5865F2  # Discord blurple — all good, keep working
_COLOR_WAITING = 0xFEE75C  # Yellow — needs owner attention
_COLOR_IDLE = 0x99AAB5  # Grey — no active sessions

# State icons and labels shown in the embed
_STATE_ICON: dict[str, str] = {
    "processing": "🟢",
    "waiting": "🟡",
}
_STATE_LABEL: dict[str, str] = {
    "processing": "Auto-processing",
    "waiting": "Waiting for input",
}

# Threads older than this are pruned from the dashboard automatically.
# Keeps the embed from accumulating stale entries after a long idle period.
_STALE_HOURS = 4


class ThreadState(str, Enum):  # noqa: UP042 — requires-python = ">=3.10", StrEnum is 3.11+
    """Lifecycle state of a Claude Code session thread."""

    PROCESSING = "processing"
    """Claude Code CLI is currently running in this thread."""

    WAITING_INPUT = "waiting"
    """Claude finished responding; awaiting the next user message."""


@dataclass
class _ThreadInfo:
    thread_id: int
    description: str
    state: ThreadState
    started_at: float = field(default_factory=time.monotonic)
    state_changed_at: float = field(default_factory=time.monotonic)


class ThreadStatusDashboard:
    """Maintains a live status embed in the bot's main channel.

    Lifecycle
    ---------
    1. Call ``await dashboard.initialize()`` once after the bot is ready.
    2. Call ``await dashboard.set_state(...)`` on every state transition.
    3. Call ``await dashboard.remove(thread_id)`` when a thread is no longer
       relevant (optional — stale entries are auto-pruned after ``_STALE_HOURS``).

    Thread safety
    -------------
    All public methods are coroutines protected by an ``asyncio.Lock``.
    """

    def __init__(
        self,
        channel: discord.TextChannel,
        owner_id: int | None = None,
    ) -> None:
        self._channel = channel
        self._owner_id = owner_id
        self._threads: dict[int, _ThreadInfo] = {}
        self._dashboard_message: discord.Message | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Post the initial (empty) dashboard embed and pin it."""
        async with self._lock:
            embed = self._build_embed()
            self._dashboard_message = await self._channel.send(embed=embed)
            try:
                await self._dashboard_message.pin()
            except discord.HTTPException:
                logger.debug(
                    "Could not pin dashboard message "
                    "(missing Manage Messages permission or pin limit reached)"
                )

    async def set_state(
        self,
        thread_id: int,
        state: ThreadState,
        description: str,
        thread: discord.Thread | discord.TextChannel | None = None,
    ) -> None:
        """Update a thread's state and refresh the dashboard embed.

        When transitioning to ``WAITING_INPUT`` for the first time, the bot
        posts a reply in *thread* mentioning the owner so Discord surfaces the
        notification immediately.

        Parameters
        ----------
        thread_id:
            Discord thread ID.
        state:
            New ``ThreadState`` value.
        description:
            Short human-readable summary (e.g. the first 100 chars of the prompt).
        thread:
            The ``discord.Thread`` object, required for owner mentions.
        """
        async with self._lock:
            prev_state = self._threads[thread_id].state if thread_id in self._threads else None

            if thread_id not in self._threads:
                self._threads[thread_id] = _ThreadInfo(
                    thread_id=thread_id,
                    description=description,
                    state=state,
                )
            else:
                info = self._threads[thread_id]
                info.state = state
                info.state_changed_at = time.monotonic()
                if description:
                    info.description = description

            # Mention owner on first WAITING_INPUT transition
            should_mention = (
                state == ThreadState.WAITING_INPUT
                and prev_state != ThreadState.WAITING_INPUT
                and self._owner_id is not None
                and thread is not None
            )

            await self._refresh_dashboard()

        # Send mention outside the lock to avoid holding it during an HTTP call
        if should_mention and thread is not None:
            try:
                await thread.send(
                    f"🟡 <@{self._owner_id}> Claude has finished — your reply is needed here."
                )
            except discord.HTTPException:
                logger.debug("Failed to send owner mention in thread %d", thread_id, exc_info=True)

    async def remove(self, thread_id: int) -> None:
        """Remove a thread from the dashboard and refresh."""
        async with self._lock:
            self._threads.pop(thread_id, None)
            await self._refresh_dashboard()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _refresh_dashboard(self) -> None:
        """Edit the dashboard message with current state.

        Must be called while the caller holds ``self._lock``.
        Falls back to posting a new message if the original is gone.
        """
        self._prune_stale()

        if self._dashboard_message is None:
            return

        embed = self._build_embed()
        try:
            await self._dashboard_message.edit(embed=embed)
        except discord.NotFound:
            logger.debug("Dashboard message was deleted; re-posting")
            try:
                self._dashboard_message = await self._channel.send(embed=embed)
            except discord.HTTPException:
                logger.warning("Failed to re-post dashboard message", exc_info=True)
        except discord.HTTPException:
            logger.debug("Failed to edit dashboard message", exc_info=True)

    def _prune_stale(self) -> None:
        """Remove threads that haven't changed state in ``_STALE_HOURS`` hours."""
        cutoff = time.monotonic() - _STALE_HOURS * 3600
        stale = [tid for tid, info in self._threads.items() if info.state_changed_at < cutoff]
        for tid in stale:
            logger.debug("Pruning stale dashboard entry for thread %d", tid)
            del self._threads[tid]

    def _build_embed(self) -> discord.Embed:
        """Construct the Discord embed reflecting current thread states."""
        if not self._threads:
            return discord.Embed(
                title="📊 Session Status",
                description="No active sessions.",
                color=_COLOR_IDLE,
            )

        any_waiting = any(t.state == ThreadState.WAITING_INPUT for t in self._threads.values())
        color = _COLOR_WAITING if any_waiting else _COLOR_PROCESSING

        embed = discord.Embed(title="📊 Session Status", color=color)

        now = time.monotonic()
        for info in sorted(self._threads.values(), key=lambda t: t.started_at):
            icon = _STATE_ICON[info.state.value]
            label = _STATE_LABEL[info.state.value]
            elapsed = int(now - info.state_changed_at)
            mins, secs = divmod(elapsed, 60)
            elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            desc_preview = info.description[:60] + ("…" if len(info.description) > 60 else "")

            embed.add_field(
                name=f"{icon} <#{info.thread_id}>",
                value=f"**{label}** · {elapsed_str} ago\n{desc_preview}",
                inline=False,
            )

        embed.set_footer(text="Updates automatically · stale entries removed after 4h")
        return embed
