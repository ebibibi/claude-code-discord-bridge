"""Shared helper for running Claude Code CLI and streaming results to a Discord thread.

Both ClaudeChatCog and SkillCommandCog need to run Claude and post results.
This module extracts that shared logic to avoid duplication.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

import discord

from ..claude.runner import ClaudeRunner
from ..claude.types import MessageType, SessionState
from ..database.repository import SessionRepository
from ..discord_ui.chunker import chunk_message
from ..discord_ui.embeds import (
    error_embed,
    session_complete_embed,
    session_start_embed,
    thinking_embed,
    tool_result_embed,
    tool_use_embed,
)
from ..discord_ui.status import StatusManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Streaming message edit interval (seconds). Discord rate limit is 5 edits/5s.
STREAM_EDIT_INTERVAL = 1.5

# Max characters before starting a new streaming message
STREAM_MAX_CHARS = 1900

# Max characters for tool result display
TOOL_RESULT_MAX_CHARS = 500


class StreamingMessageManager:
    """Manages a Discord message that gets edited as streaming text arrives.

    Creates a message on first text, then edits it at a debounced interval.
    When text exceeds Discord's limit, starts a new message.
    """

    def __init__(self, thread: discord.Thread) -> None:
        self._thread = thread
        self._current_message: discord.Message | None = None
        self._buffer: str = ""
        self._last_edit_time: float = 0
        self._pending_edit: asyncio.Task | None = None
        self._finalized: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self._buffer)

    async def append(self, text: str) -> None:
        """Append text to the streaming buffer and schedule an edit."""
        if self._finalized:
            return

        self._buffer += text

        # If buffer exceeds limit, finalize current message and start new one
        if len(self._buffer) > STREAM_MAX_CHARS and self._current_message:
            await self._flush()
            self._current_message = None
            self._buffer = self._buffer[STREAM_MAX_CHARS:]

        now = time.monotonic()
        if now - self._last_edit_time >= STREAM_EDIT_INTERVAL:
            await self._flush()
        elif not self._pending_edit or self._pending_edit.done():
            self._pending_edit = asyncio.create_task(self._delayed_flush())

    async def finalize(self) -> str:
        """Finalize the streaming message. Returns the full accumulated text."""
        self._finalized = True
        if self._pending_edit and not self._pending_edit.done():
            self._pending_edit.cancel()
        if self._buffer:
            await self._flush()
        return self._buffer

    async def _delayed_flush(self) -> None:
        """Wait for the edit interval then flush."""
        remaining = STREAM_EDIT_INTERVAL - (time.monotonic() - self._last_edit_time)
        if remaining > 0:
            await asyncio.sleep(remaining)
        if not self._finalized:
            await self._flush()

    async def _flush(self) -> None:
        """Send or edit the current message with buffer contents."""
        if not self._buffer:
            return

        display_text = self._buffer
        if len(display_text) > 2000:
            display_text = display_text[:1997] + "..."

        try:
            if self._current_message is None:
                self._current_message = await self._thread.send(display_text)
            else:
                await self._current_message.edit(content=display_text)
            self._last_edit_time = time.monotonic()
        except discord.HTTPException:
            logger.debug("Failed to edit streaming message", exc_info=True)


async def run_claude_in_thread(
    thread: discord.Thread,
    runner: ClaudeRunner,
    repo: SessionRepository | None,
    prompt: str,
    session_id: str | None,
    status: StatusManager | None = None,
) -> str | None:
    """Execute Claude Code CLI and stream results to a Discord thread.

    Args:
        thread: Discord thread to post results to.
        runner: A fresh (cloned) ClaudeRunner instance.
        repo: Session repository for persisting thread-session mappings.
              Pass None for automated workflows that don't need session persistence.
        prompt: The user's message or skill invocation.
        session_id: Optional session ID to resume. None for new sessions.
        status: Optional StatusManager for emoji reactions on the user's message.

    Returns:
        The final session_id, or None if the run failed.
    """
    state = SessionState(session_id=session_id, thread_id=thread.id)
    streamer = StreamingMessageManager(thread)

    try:
        async for event in runner.run(prompt, session_id=session_id):
            # System message: capture session_id
            if event.message_type == MessageType.SYSTEM and event.session_id:
                state.session_id = event.session_id
                if repo:
                    await repo.save(thread.id, state.session_id)
                if not session_id:
                    await thread.send(embed=session_start_embed(state.session_id))

            # Assistant message: text, thinking, or tool use
            if event.message_type == MessageType.ASSISTANT:
                # Extended thinking — post as a collapsed embed
                if event.thinking:
                    await thread.send(embed=thinking_embed(event.thinking))

                # Intermediate text — post immediately via streaming manager
                if event.text:
                    # Finalize any in-progress streaming message first
                    if streamer.has_content:
                        await streamer.finalize()
                        streamer = StreamingMessageManager(thread)

                    # Post intermediate text chunks immediately
                    for chunk in chunk_message(event.text):
                        await thread.send(chunk)
                    state.accumulated_text = event.text

                if event.tool_use:
                    if status:
                        await status.set_tool(event.tool_use.category)
                    embed = tool_use_embed(event.tool_use, in_progress=True)
                    msg = await thread.send(embed=embed)
                    state.active_tools[event.tool_use.tool_id] = msg

            # User message (tool result) — update tool embed with result
            if event.message_type == MessageType.USER and event.tool_result_id:
                if status:
                    await status.set_thinking()
                # Update the tool embed with result content
                tool_msg = state.active_tools.get(event.tool_result_id)
                if tool_msg and event.tool_result_content:
                    truncated = _truncate_result(event.tool_result_content)
                    with contextlib.suppress(discord.HTTPException):
                        await tool_msg.edit(
                            embed=tool_result_embed(
                                tool_msg.embeds[0].title or "",
                                truncated,
                            )
                        )

            # Result: session complete
            if event.is_complete:
                # Finalize any streaming message
                if streamer.has_content:
                    await streamer.finalize()

                if event.error:
                    await thread.send(embed=error_embed(event.error))
                    if status:
                        await status.set_error()
                else:
                    # Post final result text (only if different from last posted text)
                    response_text = event.text
                    if response_text and response_text != state.accumulated_text:
                        for chunk in chunk_message(response_text):
                            await thread.send(chunk)

                    await thread.send(
                        embed=session_complete_embed(event.cost_usd, event.duration_ms)
                    )
                    if status:
                        await status.set_done()

                if event.session_id:
                    if repo:
                        await repo.save(thread.id, event.session_id)
                    state.session_id = event.session_id

    except Exception:
        logger.exception("Error running Claude CLI for thread %d", thread.id)
        await thread.send(embed=error_embed("An unexpected error occurred."))
        if status:
            await status.set_error()

    return state.session_id


def _truncate_result(content: str) -> str:
    """Truncate tool result content for display."""
    if len(content) <= TOOL_RESULT_MAX_CHARS:
        return content
    return content[:TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
