"""Shared helper for running Claude Code CLI and streaming results to a Discord thread.

Both ClaudeChatCog and SkillCommandCog need to run Claude and post results.
This module extracts that shared logic to avoid duplication.

Primary API:
    run_claude_with_config(config: RunConfig) -> str | None

Legacy shim (kept for backward compatibility):
    run_claude_in_thread(thread, runner, repo, prompt, session_id, ...) -> str | None
"""

from __future__ import annotations

import contextlib
import logging
import re

import discord

from ..claude.types import MessageType, SessionState
from ..discord_ui.ask_handler import ASK_ANSWER_TIMEOUT, collect_ask_answers  # noqa: F401
from ..discord_ui.chunker import chunk_message
from ..discord_ui.embeds import (
    error_embed,
    redacted_thinking_embed,
    session_complete_embed,
    session_start_embed,
    thinking_embed,
    timeout_embed,
    tool_result_embed,
    tool_use_embed,
)
from ..discord_ui.streaming_manager import (  # noqa: F401
    STREAM_EDIT_INTERVAL,
    STREAM_MAX_CHARS,
    StreamingMessageManager,
)
from ..discord_ui.tool_timer import TOOL_TIMER_INTERVAL, LiveToolTimer  # noqa: F401
from ..lounge import build_lounge_prompt
from .run_config import RunConfig  # noqa: F401

logger = logging.getLogger(__name__)

# Max characters for tool result display.
# Sized to show ~30 lines of typical output (100 chars/line × 30 = 3000).
# The embed description limit is 4096, so this leaves room for code block markers.
TOOL_RESULT_MAX_CHARS = 3000


async def run_claude_with_config(config: RunConfig) -> str | None:
    """Execute Claude Code CLI and stream results to a Discord thread.

    This is the primary entry point. All Cogs should create a RunConfig and
    pass it here, rather than using the legacy run_claude_in_thread() shim.

    Returns:
        The final session_id, or None if the run failed.
    """
    thread = config.thread
    runner = config.runner
    prompt = config.prompt

    # Layer 3: Prepend AI Lounge context (recent messages + invitation)
    if config.lounge_repo is not None:
        try:
            recent = await config.lounge_repo.get_recent(limit=10)
            lounge_context = build_lounge_prompt(recent)
            prompt = lounge_context + "\n\n" + prompt
            logger.debug("Lounge context injected (%d recent message(s))", len(recent))
        except Exception:
            logger.warning("Failed to fetch lounge context — skipping", exc_info=True)

    # Layer 1 + 2: Register session and prepend concurrency notice
    if config.registry is not None:
        config.registry.register(thread.id, prompt[:100], runner.working_dir)
        others = config.registry.list_others(thread.id)
        notice = config.registry.build_concurrency_notice(thread.id)
        prompt = notice + "\n\n" + prompt
        logger.info(
            "Concurrency notice injected for thread %d (%d other active session(s), dir=%s)",
            thread.id,
            len(others),
            runner.working_dir or "(default)",
        )
    else:
        logger.debug("No session registry — concurrency notice skipped for thread %d", thread.id)

    state = SessionState(session_id=config.session_id, thread_id=thread.id)
    streamer = StreamingMessageManager(thread)

    # Set when AskUserQuestion is detected mid-stream. After the runner is
    # interrupted and the stream drains, we show Discord UI and resume.
    pending_ask = None

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
        async for event in runner.run(prompt, session_id=config.session_id):
            # System message: capture session_id
            if event.message_type == MessageType.SYSTEM and event.session_id:
                state.session_id = event.session_id
                if config.repo:
                    await config.repo.save(thread.id, state.session_id)
                if not config.session_id and not session_start_sent:
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
                    if config.status:
                        await config.status.set_tool(event.tool_use.category)
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
                if config.status:
                    await config.status.set_thinking()
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
                    if config.status:
                        await config.status.set_error()
                else:
                    # Post final result text only if no assistant text was already sent.
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
                    if config.status:
                        await config.status.set_done()

                if event.session_id:
                    if config.repo:
                        await config.repo.save(thread.id, event.session_id)
                    state.session_id = event.session_id

    except Exception:
        logger.exception("Error running Claude CLI for thread %d", thread.id)
        await thread.send(embed=error_embed("An unexpected error occurred."))
        if config.status:
            await config.status.set_error()
        return state.session_id
    finally:
        # Cancel any timers that were not already stopped by tool_result events.
        for task in state.active_timers.values():
            if not task.done():
                task.cancel()
        state.active_timers.clear()

        if config.registry is not None:
            config.registry.unregister(thread.id)

    # After the stream ends, handle pending AskUserQuestion by showing Discord
    # UI and resuming the session with the user's answer.
    if pending_ask and state.session_id:
        answer_prompt = await collect_ask_answers(
            thread, pending_ask, state.session_id, ask_repo=config.ask_repo
        )
        if answer_prompt:
            logger.info(
                "Resuming session %s after AskUserQuestion answer",
                state.session_id,
            )
            return await run_claude_with_config(config.with_prompt(answer_prompt))

    return state.session_id


async def run_claude_in_thread(
    thread: discord.Thread,
    runner,
    repo,
    prompt: str,
    session_id: str | None,
    status=None,
    registry=None,
    ask_repo=None,
    lounge_repo=None,
) -> str | None:
    """Backward-compatible shim. Prefer run_claude_with_config() for new code."""
    config = RunConfig(
        thread=thread,
        runner=runner,
        prompt=prompt,
        session_id=session_id,
        repo=repo,
        status=status,
        registry=registry,
        ask_repo=ask_repo,
        lounge_repo=lounge_repo,
    )
    return await run_claude_with_config(config)


def _truncate_result(content: str) -> str:
    """Truncate tool result content for display."""
    if len(content) <= TOOL_RESULT_MAX_CHARS:
        return content
    return content[:TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"


_TIMEOUT_PATTERN = re.compile(r"Timed out after (\d+) seconds")


def _make_error_embed(error: str) -> discord.Embed:
    """Return a timeout_embed for timeout errors, error_embed otherwise."""
    m = _TIMEOUT_PATTERN.match(error)
    if m:
        return timeout_embed(int(m.group(1)))
    return error_embed(error)
