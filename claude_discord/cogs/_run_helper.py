"""Shared helper for running Claude Code CLI and streaming results to a Discord thread.

Both ClaudeChatCog and SkillCommandCog need to run Claude and post results.
This module is the thin orchestration layer that:
1. Builds ephemeral system context (lounge + concurrency notice) via --append-system-prompt
2. Delegates event processing to EventProcessor
3. Handles AskUserQuestion flow (recursive resume)

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

from ..discord_ui.ask_handler import ASK_ANSWER_TIMEOUT, collect_ask_answers  # noqa: F401
from ..discord_ui.embeds import error_embed, timeout_embed
from ..discord_ui.streaming_manager import (  # noqa: F401
    STREAM_EDIT_INTERVAL,
    STREAM_MAX_CHARS,
    StreamingMessageManager,
)
from ..discord_ui.tool_timer import TOOL_TIMER_INTERVAL, LiveToolTimer  # noqa: F401
from ..lounge import build_lounge_prompt
from .event_processor import EventProcessor
from .run_config import RunConfig  # noqa: F401

logger = logging.getLogger(__name__)

# Max characters for tool result display (re-exported for backward compat).
TOOL_RESULT_MAX_CHARS = 3000

_TIMEOUT_PATTERN = re.compile(r"Timed out after (\d+) seconds")


def _make_error_embed(error: str) -> discord.Embed:
    """Return a timeout_embed for timeout errors, error_embed otherwise."""
    m = _TIMEOUT_PATTERN.match(error)
    if m:
        return timeout_embed(int(m.group(1)))
    return error_embed(error)


def _truncate_result(content: str) -> str:
    """Truncate tool result content for display (re-exported for backward compat)."""
    if len(content) <= TOOL_RESULT_MAX_CHARS:
        return content
    return content[:TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"


async def _build_system_context(config: RunConfig) -> str | None:
    """Build ephemeral system context from AI Lounge and concurrency notice.

    Returns a string to inject via --append-system-prompt, or None if no context
    is available. Injecting as a system prompt (rather than prepending to the user
    message) prevents this ephemeral metadata from accumulating in session history,
    which would otherwise cause "Prompt is too long" errors over long conversations.
    """
    parts: list[str] = []

    # Layer 3: AI Lounge context (recent messages + invitation).
    if config.lounge_repo is not None:
        try:
            recent = await config.lounge_repo.get_recent(limit=10)
            lounge_context = build_lounge_prompt(recent)
            parts.append(lounge_context)
            logger.debug("Lounge context built (%d recent message(s))", len(recent))
        except Exception:
            logger.warning("Failed to fetch lounge context — skipping", exc_info=True)

    # Layer 1 + 2: Register session and build concurrency notice.
    if config.registry is not None:
        config.registry.register(config.thread.id, config.prompt[:100], config.runner.working_dir)
        others = config.registry.list_others(config.thread.id)
        notice = config.registry.build_concurrency_notice(config.thread.id)
        parts.append(notice)
        logger.info(
            "Concurrency notice built for thread %d (%d other active session(s), dir=%s)",
            config.thread.id,
            len(others),
            config.runner.working_dir or "(default)",
        )
    else:
        logger.debug(
            "No session registry — concurrency notice skipped for thread %d", config.thread.id
        )

    return "\n\n".join(parts) if parts else None


async def _cleanup_session_worktree(config: RunConfig) -> None:
    """Remove the session worktree for this thread if it is clean.

    Runs git operations in a thread pool to avoid blocking the event loop.
    Logs the outcome but never raises — cleanup failures are non-fatal.
    """
    import asyncio

    assert config.worktree_manager is not None  # caller ensures this

    try:
        result = await asyncio.to_thread(
            config.worktree_manager.cleanup_for_thread,
            config.thread.id,
        )
        if result.removed:
            logger.info(
                "Cleaned up session worktree for thread %d: %s",
                config.thread.id,
                result.path,
            )
        elif result.reason == "worktree directory does not exist":
            # Normal case — Claude didn't create a worktree
            pass
        else:
            logger.warning(
                "Could not clean up worktree for thread %d (%s): %s",
                config.thread.id,
                result.path,
                result.reason,
            )
            # Notify the Discord thread if there are uncommitted changes
            if "uncommitted changes" in result.reason:
                with contextlib.suppress(Exception):
                    await config.thread.send(
                        f"⚠️ **Worktree not cleaned up** — `{result.path}` has uncommitted "
                        f"changes. Please commit or stash them, then run:\n"
                        f"```\ngit worktree remove {result.path}\n```"
                    )
    except Exception:
        logger.exception("Unexpected error during worktree cleanup for thread %d", config.thread.id)


async def run_claude_with_config(config: RunConfig) -> str | None:
    """Execute Claude Code CLI and stream results to a Discord thread.

    This is the primary entry point. All Cogs should create a RunConfig and
    pass it here, rather than using the legacy run_claude_in_thread() shim.

    Returns:
        The final session_id, or None if the run failed.
    """
    system_context = await _build_system_context(config)
    runner = (
        config.runner.clone(append_system_prompt=system_context)
        if system_context
        else config.runner
    )
    processor = EventProcessor(config)

    try:
        async for event in runner.run(config.prompt, session_id=config.session_id):
            if processor.should_drain:
                continue
            await processor.process(event)
    except Exception:
        logger.exception("Error running Claude CLI for thread %d", config.thread.id)
        # Wrap Discord sends in suppress — the connection may already be closed
        # (e.g. ServerDisconnectedError on bot shutdown), and sending would fail too.
        with contextlib.suppress(Exception):
            await config.thread.send(embed=error_embed("An unexpected error occurred."))
        if config.status:
            with contextlib.suppress(Exception):
                await config.status.set_error()
        return processor.session_id
    finally:
        await processor.finalize()
        if config.registry is not None:
            config.registry.unregister(config.thread.id)
        if config.worktree_manager is not None:
            await _cleanup_session_worktree(config)

    # After the stream ends, handle pending AskUserQuestion by showing Discord
    # UI and resuming the session with the user's answer.
    if processor.pending_ask and processor.session_id:
        answer_prompt = await collect_ask_answers(
            config.thread,
            processor.pending_ask,
            processor.session_id,
            ask_repo=config.ask_repo,
        )
        if answer_prompt:
            logger.info(
                "Resuming session %s after AskUserQuestion answer",
                processor.session_id,
            )
            return await run_claude_with_config(config.with_prompt(answer_prompt))

    return processor.session_id


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
