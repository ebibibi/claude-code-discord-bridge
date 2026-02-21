"""Event processor for Claude Code stream-json output.

Encapsulates all the state and logic for processing a single Claude Code
CLI session: tracking session IDs, streaming text to Discord, posting tool
embeds, handling AskUserQuestion interrupts, and posting the final result.

This class is extracted from the monolithic run_claude_in_thread() function
so that individual event handlers can be tested in isolation.
"""

from __future__ import annotations

import contextlib
import logging

import discord

from ..claude.types import AskQuestion, MessageType, SessionState, StreamEvent
from ..discord_ui.chunker import chunk_message
from ..discord_ui.embeds import (
    redacted_thinking_embed,
    session_start_embed,
    thinking_embed,
    tool_result_embed,
    tool_use_embed,
)
from ..discord_ui.streaming_manager import StreamingMessageManager
from ..discord_ui.tool_timer import LiveToolTimer
from .run_config import RunConfig

logger = logging.getLogger(__name__)

# Max characters for tool result display.
# Sized to show ~30 lines of typical output (100 chars/line × 30 = 3000).
# The embed description limit is 4096, so this leaves room for code block markers.
_TOOL_RESULT_MAX_CHARS = 3000


def _truncate_result(content: str) -> str:
    """Truncate tool result content for display."""
    if len(content) <= _TOOL_RESULT_MAX_CHARS:
        return content
    return content[:_TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"


class EventProcessor:
    """Processes stream-json events and dispatches Discord actions.

    One instance per Claude Code session run. Call process(event) for each
    event from the runner; call finalize() in a finally block to clean up.

    State machine:
    - session_start_sent: prevents duplicate session start embeds
    - assistant_text_sent: prevents duplicate result text posts
    - pending_ask: set when AskUserQuestion detected; caller should drain runner

    Example usage (see _run_helper.run_claude_with_config for the full flow)::

        processor = EventProcessor(config)
        try:
            async for event in config.runner.run(prompt):
                if processor.should_drain:
                    continue
                await processor.process(event)
        finally:
            await processor.finalize()

        if processor.pending_ask and processor.session_id:
            # Handle AskUserQuestion (see run_helper)
            ...

        return processor.session_id
    """

    def __init__(self, config: RunConfig) -> None:
        self._config = config
        self._state = SessionState(
            session_id=config.session_id,
            thread_id=config.thread.id,
        )
        self._streamer = StreamingMessageManager(config.thread)

        # Guards against duplicate embeds/messages in the same run.
        self._session_start_sent: bool = False
        self._assistant_text_sent: bool = False

        # Set when AskUserQuestion is detected. Caller should drain the runner
        # (skip events) then handle the ask after the stream ends.
        self._pending_ask: list[AskQuestion] | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        """The current session ID, updated as SYSTEM events arrive."""
        return self._state.session_id

    @property
    def pending_ask(self) -> list[AskQuestion] | None:
        """Set when AskUserQuestion was detected. None otherwise."""
        return self._pending_ask

    @property
    def should_drain(self) -> bool:
        """True while the runner should be drained (AskUserQuestion detected)."""
        return self._pending_ask is not None

    @property
    def assistant_text_sent(self) -> bool:
        """True if assistant text was already streamed to Discord."""
        return self._assistant_text_sent

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def process(self, event: StreamEvent) -> None:
        """Dispatch a single stream event to the appropriate handler."""
        if event.message_type == MessageType.SYSTEM:
            await self._on_system(event)
        elif event.message_type == MessageType.ASSISTANT:
            await self._on_assistant(event)
        elif event.message_type == MessageType.USER:
            await self._on_tool_result(event)

        if event.is_complete:
            await self._on_complete(event)

    async def finalize(self) -> None:
        """Cancel any running timers. Call in a finally block."""
        for task in self._state.active_timers.values():
            if not task.done():
                task.cancel()
        self._state.active_timers.clear()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_system(self, event: StreamEvent) -> None:
        """Handle SYSTEM events — capture session_id and post start embed."""
        if not event.session_id:
            return

        self._state.session_id = event.session_id
        if self._config.repo:
            await self._config.repo.save(self._config.thread.id, self._state.session_id)

        # Guard: post session_start_embed only once (Claude can emit multiple SYSTEM events).
        if not self._config.session_id and not self._session_start_sent:
            await self._config.thread.send(embed=session_start_embed(self._state.session_id))
            self._session_start_sent = True

    async def _on_assistant(self, event: StreamEvent) -> None:
        """Handle ASSISTANT events — thinking, streaming text, tool use."""
        # Extended thinking — only post on complete events (not partials).
        if event.thinking and not event.is_partial:
            await self._config.thread.send(embed=thinking_embed(event.thinking))

        # Redacted thinking — only post on complete events.
        if event.has_redacted_thinking and not event.is_partial:
            await self._config.thread.send(embed=redacted_thinking_embed())

        # Text streaming — compute delta from last partial, edit in place.
        if event.text:
            await self._handle_text(event)

        # Tool use — post embed and start live timer.
        if event.tool_use:
            await self._handle_tool_use(event)

        # AskUserQuestion — set pending and signal caller to interrupt runner.
        if event.ask_questions:
            self._pending_ask = event.ask_questions
            await self._config.runner.interrupt()

    async def _on_tool_result(self, event: StreamEvent) -> None:
        """Handle USER events (tool results) — cancel timer, update embed."""
        if not event.tool_result_id:
            return

        if self._config.status:
            await self._config.status.set_thinking()

        # Cancel the elapsed-time timer for this tool.
        timer_task = self._state.active_timers.pop(event.tool_result_id, None)
        if timer_task and not timer_task.done():
            timer_task.cancel()

        # Update the tool embed with result content.
        tool_msg = self._state.active_tools.get(event.tool_result_id)
        if tool_msg and event.tool_result_content:
            truncated = _truncate_result(event.tool_result_content)
            with contextlib.suppress(discord.HTTPException):
                await tool_msg.edit(
                    embed=tool_result_embed(
                        tool_msg.embeds[0].title or "",
                        truncated,
                    )
                )

    async def _on_complete(self, event: StreamEvent) -> None:
        """Handle RESULT events — finalize streaming, post summary embed."""
        from ..discord_ui.embeds import (
            session_complete_embed,
        )
        from ..discord_ui.streaming_manager import StreamingMessageManager
        from ._run_helper import _make_error_embed

        # Finalize any in-progress streaming message.
        if self._streamer.has_content:
            await self._streamer.finalize()
            self._assistant_text_sent = True

        if event.error:
            await self._config.thread.send(embed=_make_error_embed(event.error))
            if self._config.status:
                await self._config.status.set_error()
        else:
            # Post final result text only if no assistant text was already sent.
            response_text = event.text
            if response_text and not self._assistant_text_sent:
                for chunk in chunk_message(response_text):
                    await self._config.thread.send(chunk)

            await self._config.thread.send(
                embed=session_complete_embed(
                    event.cost_usd,
                    event.duration_ms,
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_read_tokens,
                )
            )
            if self._config.status:
                await self._config.status.set_done()

        if event.session_id:
            if self._config.repo:
                await self._config.repo.save(self._config.thread.id, event.session_id)
            self._state.session_id = event.session_id

        # Reset for potential next streamer
        self._streamer = StreamingMessageManager(self._config.thread)

    # ------------------------------------------------------------------
    # Text streaming helpers
    # ------------------------------------------------------------------

    async def _handle_text(self, event: StreamEvent) -> None:
        """Stream text to Discord, computing deltas for partial events."""
        assert event.text is not None

        if event.is_partial:
            delta = event.text[len(self._state.partial_text) :]
            self._state.partial_text = event.text
            if delta:
                await self._streamer.append(delta)
        else:
            # Complete text block: flush the streamer with any remaining delta.
            delta = event.text[len(self._state.partial_text) :]
            if self._streamer.has_content:
                if delta:
                    await self._streamer.append(delta)
                await self._streamer.finalize()
                self._streamer = StreamingMessageManager(self._config.thread)
            else:
                # No partial events arrived — post the full text directly.
                for chunk in chunk_message(event.text):
                    await self._config.thread.send(chunk)
            self._state.partial_text = ""
            self._state.accumulated_text = event.text
            self._assistant_text_sent = True
            await self._bump_stop()

    async def _handle_tool_use(self, event: StreamEvent) -> None:
        """Post tool use embed and start the live timer."""
        assert event.tool_use is not None

        # Finalize any in-progress streaming text before the tool embed.
        if self._streamer.has_content:
            await self._streamer.finalize()
            self._streamer = StreamingMessageManager(self._config.thread)
        self._state.partial_text = ""

        if self._config.status:
            await self._config.status.set_tool(event.tool_use.category)

        embed = tool_use_embed(event.tool_use, in_progress=True)
        msg = await self._config.thread.send(embed=embed)
        self._state.active_tools[event.tool_use.tool_id] = msg

        timer = LiveToolTimer(msg, event.tool_use)
        self._state.active_timers[event.tool_use.tool_id] = timer.start()

        await self._bump_stop()

    async def _bump_stop(self) -> None:
        """Move the Stop button to the bottom of the thread if configured."""
        if self._config.stop_view:
            await self._config.stop_view.bump(self._config.thread)
