"""Streaming message manager for Discord threads.

Manages a Discord message that gets edited as streaming text arrives from
the Claude Code CLI. Created on first text, then edited at a debounced
interval to respect Discord rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord

logger = logging.getLogger(__name__)

# Streaming message edit interval (seconds). Discord rate limit is 5 edits/5s.
STREAM_EDIT_INTERVAL = 1.5

# Max characters before starting a new streaming message
STREAM_MAX_CHARS = 1900


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
        self._pending_edit: asyncio.Task[None] | None = None
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
        except Exception:
            # Catch all exceptions including aiohttp.ClientError (e.g. ServerDisconnectedError
            # on bot shutdown) which is not a subclass of discord.HTTPException.
            logger.debug("Failed to send/edit streaming message", exc_info=True)
