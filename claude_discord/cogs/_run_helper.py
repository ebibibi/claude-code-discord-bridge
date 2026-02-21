"""Shared helper for running Claude Code CLI and streaming results to a Discord thread.

Both ClaudeChatCog and SkillCommandCog need to run Claude and post results.
This module extracts that shared logic to avoid duplication.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time

import discord

from ..claude.runner import ClaudeRunner
from ..claude.types import AskQuestion, MessageType, SessionState, ToolUseEvent
from ..concurrency import SessionRegistry
from ..database.ask_repo import PendingAskRepository
from ..database.lounge_repo import LoungeRepository
from ..database.repository import SessionRepository
from ..discord_ui.ask_bus import ask_bus as _ask_bus
from ..discord_ui.ask_view import AskView
from ..discord_ui.chunker import chunk_message
from ..discord_ui.embeds import (
    ask_embed,
    error_embed,
    redacted_thinking_embed,
    session_complete_embed,
    session_start_embed,
    thinking_embed,
    timeout_embed,
    tool_result_embed,
    tool_use_embed,
)
from ..discord_ui.status import StatusManager
from ..lounge import build_lounge_prompt

logger = logging.getLogger(__name__)

# Streaming message edit interval (seconds). Discord rate limit is 5 edits/5s.
STREAM_EDIT_INTERVAL = 1.5

# Max characters before starting a new streaming message
STREAM_MAX_CHARS = 1900

# Max characters for tool result display.
# Sized to show ~30 lines of typical output (100 chars/line × 30 = 3000).
# The embed description limit is 4096, so this leaves room for code block markers.
TOOL_RESULT_MAX_CHARS = 3000

# How often to update in-progress tool embeds with elapsed time (seconds).
# Gives users visibility into long-running commands (builds, auth flows, etc.).
TOOL_TIMER_INTERVAL = 10


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


class LiveToolTimer:
    """Periodically edits a Discord embed to show elapsed execution time.

    Started when a tool_use event is received; cancelled when the corresponding
    tool_result arrives. For commands that finish quickly (<TOOL_TIMER_INTERVAL s)
    the timer fires zero times, so there is no overhead for fast tools.

    This provides basic visibility into long-running operations — the user can
    see "🔧 Running: az login... (10s)" ticking up rather than a frozen embed.
    Note: intermediate stdout from Bash is not exposed by the stream-json
    protocol, so only elapsed time (not actual output) is available here.
    """

    def __init__(self, msg: discord.Message, tool: ToolUseEvent) -> None:
        self._msg = msg
        self._tool = tool
        self._start = time.monotonic()

    def start(self) -> asyncio.Task[None]:
        """Schedule the timer loop and return the Task so callers can cancel it."""
        return asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(TOOL_TIMER_INTERVAL)
                elapsed = int(time.monotonic() - self._start)
                with contextlib.suppress(discord.HTTPException):
                    await self._msg.edit(
                        embed=tool_use_embed(self._tool, in_progress=True, elapsed_s=elapsed)
                    )
        except asyncio.CancelledError:
            pass


async def run_claude_in_thread(
    thread: discord.Thread,
    runner: ClaudeRunner,
    repo: SessionRepository | None,
    prompt: str,
    session_id: str | None,
    status: StatusManager | None = None,
    registry: SessionRegistry | None = None,
    ask_repo: PendingAskRepository | None = None,
    lounge_repo: LoungeRepository | None = None,
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
        registry: Optional SessionRegistry for concurrency awareness.
                  When provided, the session is registered during execution and
                  a concurrency notice is prepended to the prompt.

    Returns:
        The final session_id, or None if the run failed.
    """
    # Layer 3: Prepend AI Lounge context (recent messages + invitation)
    if lounge_repo is not None:
        try:
            recent = await lounge_repo.get_recent(limit=10)
            lounge_context = build_lounge_prompt(recent)
            prompt = lounge_context + "\n\n" + prompt
            logger.debug("Lounge context injected (%d recent message(s))", len(recent))
        except Exception:
            logger.warning("Failed to fetch lounge context — skipping", exc_info=True)

    # Layer 1 + 2: Register session and prepend concurrency notice
    if registry is not None:
        registry.register(thread.id, prompt[:100], runner.working_dir)
        others = registry.list_others(thread.id)
        notice = registry.build_concurrency_notice(thread.id)
        prompt = notice + "\n\n" + prompt
        logger.info(
            "Concurrency notice injected for thread %d (%d other active session(s), dir=%s)",
            thread.id,
            len(others),
            runner.working_dir or "(default)",
        )
    else:
        logger.debug("No session registry — concurrency notice skipped for thread %d", thread.id)

    state = SessionState(session_id=session_id, thread_id=thread.id)
    streamer = StreamingMessageManager(thread)

    # Set when AskUserQuestion is detected mid-stream. After the runner is
    # interrupted and the stream drains, we show Discord UI and resume.
    pending_ask: list[AskQuestion] | None = None

    # Guard against sending session_start_embed more than once.
    # Claude Code emits multiple SYSTEM events per session (init + hook feedback),
    # and --include-partial-messages can produce partial+complete events for hooks.
    # Without this guard, each SYSTEM event with session_id triggers a duplicate embed.
    session_start_sent: bool = False

    # Guard against re-sending text that was already streamed to Discord.
    # The RESULT event carries a `result` field that may differ subtly from the
    # last ASSISTANT event text (trailing whitespace, join differences, etc.).
    # A string comparison guard is fragile; tracking whether we sent text is safer.
    assistant_text_sent: bool = False

    try:
        async for event in runner.run(prompt, session_id=session_id):
            # System message: capture session_id
            if event.message_type == MessageType.SYSTEM and event.session_id:
                state.session_id = event.session_id
                if repo:
                    await repo.save(thread.id, state.session_id)
                if not session_id and not session_start_sent:
                    await thread.send(embed=session_start_embed(state.session_id))
                    session_start_sent = True

            # While draining a runner that was interrupted for AskUserQuestion,
            # skip all further event processing.
            if pending_ask is not None:
                continue

            # Assistant message: text, thinking, or tool use
            if event.message_type == MessageType.ASSISTANT:
                # Extended thinking — skip partial events to avoid flooding with duplicate
                # embeds. With --include-partial-messages, thinking blocks arrive many times
                # as Claude generates them; post only the final complete version.
                if event.thinking and not event.is_partial:
                    await thread.send(embed=thinking_embed(event.thinking))

                # Redacted thinking — post only on complete messages
                if event.has_redacted_thinking and not event.is_partial:
                    await thread.send(embed=redacted_thinking_embed())

                # Text — stream into one Discord message, editing in-place as chunks arrive.
                # Partial events extend the streaming message; complete events finalize it.
                # stream-json delivers the full accumulated text on every partial event, so
                # we compute the delta to feed into StreamingMessageManager.append().
                if event.text:
                    if event.is_partial:
                        delta = event.text[len(state.partial_text) :]
                        state.partial_text = event.text
                        if delta:
                            await streamer.append(delta)
                    else:
                        # Complete text block: flush the streamer with any remaining delta
                        delta = event.text[len(state.partial_text) :]
                        if streamer.has_content:
                            if delta:
                                await streamer.append(delta)
                            await streamer.finalize()
                            streamer = StreamingMessageManager(thread)
                        else:
                            # No partial events arrived — post the full text directly
                            for chunk in chunk_message(event.text):
                                await thread.send(chunk)
                        state.partial_text = ""
                        state.accumulated_text = event.text
                        assistant_text_sent = True

                if event.tool_use:
                    # Finalize any in-progress streaming text before the tool embed
                    if streamer.has_content:
                        await streamer.finalize()
                        streamer = StreamingMessageManager(thread)
                    state.partial_text = ""
                    if status:
                        await status.set_tool(event.tool_use.category)
                    embed = tool_use_embed(event.tool_use, in_progress=True)
                    msg = await thread.send(embed=embed)
                    state.active_tools[event.tool_use.tool_id] = msg
                    timer = LiveToolTimer(msg, event.tool_use)
                    state.active_timers[event.tool_use.tool_id] = timer.start()

                # AskUserQuestion detected — interrupt the runner and await UI
                if event.ask_questions:
                    pending_ask = event.ask_questions
                    await runner.interrupt()
                    continue

            # User message (tool result) — cancel timer and update tool embed
            if event.message_type == MessageType.USER and event.tool_result_id:
                if status:
                    await status.set_thinking()
                # Stop the elapsed-time timer for this tool (if any)
                timer_task = state.active_timers.pop(event.tool_result_id, None)
                if timer_task and not timer_task.done():
                    timer_task.cancel()
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
                # Finalize any streaming message (shouldn't have content here normally,
                # but guard against edge cases where the ASSISTANT complete event was missed)
                if streamer.has_content:
                    await streamer.finalize()
                    assistant_text_sent = True

                if event.error:
                    await thread.send(embed=_make_error_embed(event.error))
                    if status:
                        await status.set_error()
                else:
                    # Post final result text only if no assistant text was already sent.
                    # The RESULT event's `result` field can differ subtly from the last
                    # ASSISTANT event text (trailing whitespace, join differences), so a
                    # string comparison guard is unreliable. The flag is the source of truth.
                    response_text = event.text
                    if response_text and not assistant_text_sent:
                        for chunk in chunk_message(response_text):
                            await thread.send(chunk)

                    await thread.send(
                        embed=session_complete_embed(
                            event.cost_usd,
                            event.duration_ms,
                            event.input_tokens,
                            event.output_tokens,
                            event.cache_read_tokens,
                        )
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
    finally:
        # Cancel any timers that were not already stopped by tool_result events.
        # This guards against early exits (errors, interrupts) leaving ghost tasks.
        for task in state.active_timers.values():
            if not task.done():
                task.cancel()
        state.active_timers.clear()

        if registry is not None:
            registry.unregister(thread.id)

    # After the stream ends, handle pending AskUserQuestion by showing Discord
    # UI and resuming the session with the user's answer.
    if pending_ask and state.session_id:
        answer_prompt = await _collect_ask_answers(
            thread, pending_ask, state.session_id, ask_repo=ask_repo
        )
        if answer_prompt:
            logger.info(
                "Resuming session %s after AskUserQuestion answer",
                state.session_id,
            )
            return await run_claude_in_thread(
                thread=thread,
                runner=runner.clone(),
                repo=repo,
                prompt=answer_prompt,
                session_id=state.session_id,
                status=status,
                registry=registry,
                ask_repo=ask_repo,
                lounge_repo=lounge_repo,
            )

    return state.session_id


def _truncate_result(content: str) -> str:
    """Truncate tool result content for display."""
    if len(content) <= TOOL_RESULT_MAX_CHARS:
        return content
    return content[:TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"


_TIMEOUT_PATTERN = re.compile(r"Timed out after (\d+) seconds")


# How long to wait for the user to answer (seconds).  24 hours lets users
# step away for the day and come back without "Interaction Failed" errors.
ASK_ANSWER_TIMEOUT = 86_400  # 24 h


async def _collect_ask_answers(
    thread: discord.Thread,
    questions: list[AskQuestion],
    session_id: str,
    ask_repo: PendingAskRepository | None = None,
) -> str | None:
    """Show Discord UI for each question and return the formatted answer string.

    Processes questions sequentially (one at a time).  For each question:
    1. Saves it to the DB (for bot-restart recovery).
    2. Registers a Queue with ask_bus and shows the AskView.
    3. Awaits the answer for up to 24 hours via asyncio.wait_for.
    4. Cleans up the DB entry once answered or timed out.

    Returns a human-readable string to inject as the next human turn, or None
    if no question received an answer.
    """
    # Serialise questions once for DB storage.
    questions_dicts = [
        {
            "question": q.question,
            "header": q.header,
            "multi_select": q.multi_select,
            "options": [{"label": o.label, "description": o.description} for o in q.options],
        }
        for q in questions
    ]

    parts: list[str] = []
    for q_idx, q in enumerate(questions):
        # Persist so on_ready can re-register the view after a bot restart.
        if ask_repo is not None:
            await ask_repo.save(
                thread_id=thread.id,
                session_id=session_id,
                questions=questions_dicts,
                question_idx=q_idx,
            )

        # Register a waiter in the bus before showing the view so there is no
        # race between the user clicking and the queue being registered.
        answer_queue = _ask_bus.register(thread.id)

        view = AskView(q, thread_id=thread.id, q_idx=q_idx, ask_repo=ask_repo)
        msg = await thread.send(embed=ask_embed(q.question, q.header), view=view)

        try:
            selected = await asyncio.wait_for(answer_queue.get(), timeout=ASK_ANSWER_TIMEOUT)
        except TimeoutError:
            _ask_bus.unregister(thread.id)
            if ask_repo is not None:
                await ask_repo.delete(thread.id)
            # Remove buttons from the timed-out message so they stay inert.
            with contextlib.suppress(discord.HTTPException):
                await msg.edit(
                    content="-# ⏰ Question timed out — please send a new message to continue.",
                    embed=None,
                    view=None,
                )
            logger.info(
                "AskUserQuestion timed out after %ds for thread %d: %r",
                ASK_ANSWER_TIMEOUT,
                thread.id,
                q.question,
            )
            continue
        finally:
            _ask_bus.unregister(thread.id)

        if ask_repo is not None:
            await ask_repo.delete(thread.id)

        if not selected:
            continue

        answer_text = ", ".join(selected)
        parts.append(f"**{q.question}**\nAnswer: {answer_text}")

    if not parts:
        return None

    return (
        "[Response to AskUserQuestion]\n\n"
        + "\n\n".join(parts)
        + "\n\nPlease continue based on these answers."
    )


def _make_error_embed(error: str) -> discord.Embed:
    """Return a timeout_embed for timeout errors, error_embed otherwise."""
    m = _TIMEOUT_PATTERN.match(error)
    if m:
        return timeout_embed(int(m.group(1)))
    return error_embed(error)
