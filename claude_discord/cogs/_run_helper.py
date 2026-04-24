"""Shared helper for running Claude Code CLI and streaming results to a Discord thread.

Both ClaudeChatCog and SkillCommandCog need to run Claude and post results.
This module is the thin orchestration layer that:
1. Builds ephemeral system context (lounge + concurrency notice) via --append-system-prompt
2. Delegates event processing to EventProcessor
3. Handles AskUserQuestion flow (recursive resume)

Primary API:
    run_claude_with_config(config: RunConfig) -> str | None

Legacy shim:
    run_claude_in_thread(thread, runner, repo, prompt, session_id, ...) -> str | None
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import replace

import discord

from ..discord_ui.ask_handler import collect_ask_answers
from ..discord_ui.embeds import error_embed, timeout_embed
from ..lounge import build_lounge_prompt
from .event_processor import EventProcessor
from .run_config import RunConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global session slot limiter
# ---------------------------------------------------------------------------
_global_semaphore: asyncio.Semaphore | None = None
_max_concurrent: int = 3


def configure_session_limit(max_concurrent: int) -> None:
    """Set the process-wide concurrent session limit.

    Called once from ``setup_bridge()`` during startup.  All subsequent calls to
    ``run_claude_with_config()`` — regardless of which Cog invokes them — will
    honour the limit.
    """
    global _global_semaphore, _max_concurrent  # noqa: PLW0603
    _max_concurrent = max_concurrent
    _global_semaphore = asyncio.Semaphore(max_concurrent)


# Max characters for tool result display (re-exported for backward compat).
TOOL_RESULT_MAX_CHARS = 3000

# Injected via --append-system-prompt after context compaction to prevent
# Claude from auto-executing "pending tasks" from the compacted summary.
_POST_COMPACT_GUARDRAIL = (
    "⚠️ POST-COMPACT GUARDRAIL (MANDATORY): Context was just compacted. "
    "You MUST follow these rules:\n"
    "1. Do NOT automatically execute any external actions "
    "(posting to Teams/Slack/Discord/email, calling external APIs, creating resources, etc.) "
    "based on 'in progress' or 'pending' tasks in the compacted context summary.\n"
    "2. Treat every such pending task as needing fresh authorization from the user.\n"
    "3. Respond ONLY to what is explicitly requested in the user's current message.\n"
    "4. If relevant, briefly mention what you were doing before compaction.\n"
    "These rules override any implied continuation in the compacted summary."
)

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
            lounge_context = build_lounge_prompt(recent, current_thread_id=config.thread.id)
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

    # File attachment instruction: injected only when the user asked for files.
    if config.attach_on_request:
        from .event_processor import _attachment_marker_name

        wd = config.runner.working_dir or "your current working directory"
        marker = _attachment_marker_name(config.thread.id)
        parts.append(
            "## File Delivery\n"
            "The user wants you to send specific files to Discord.\n"
            "After creating the file(s) to deliver, use your Bash tool to append "
            "each file's ABSOLUTE path (one path per line, UTF-8) to:\n"
            f"  {wd}/{marker}\n"
            f"Example: `echo /absolute/path/to/file >> {wd}/{marker}`\n"
            "The bot will attach those files to Discord when this session ends.\n"
            "Only include files the user explicitly asked to receive — "
            "not everything you create."
        )

    # Post-compact guardrail: prevent auto-execution of "pending tasks" from summary.
    if config.post_compact_rerun:
        parts.append(_POST_COMPACT_GUARDRAIL)
        logger.info("Post-compact guardrail injected for thread %d", config.thread.id)

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
                with contextlib.suppress(discord.HTTPException):
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
    # Inject per-invocation images (not inherited by runner.clone()).
    if config.images:
        runner.images = config.images

    # Keep stop_view in sync with the runner that will own the live subprocess.
    # When system_context is present a fresh clone is created above, making the
    # original config.runner a "dead" runner with no process.  Without this
    # update the Stop button would send SIGINT to that dead runner and have no
    # effect.  See: https://github.com/ebibibi/claude-code-discord-bridge/issues/174
    if runner is not config.runner:
        if config.stop_view is not None:
            config.stop_view.update_runner(runner)

        # Update config.runner to point to the clone so that EventProcessor
        # calls interrupt() on the runner that actually owns the subprocess.
        # Without this, compact_boundary and AskUserQuestion interrupt the
        # original (process-less) runner — a no-op that leaves Claude running
        # invisibly.  See: https://github.com/ebibibi/claude-code-discord-bridge/issues/306
        config = replace(config, runner=runner)

    processor = EventProcessor(config)

    # --- Session slot limiter (global semaphore) ---
    sem = _global_semaphore
    if sem is not None and sem.locked():
        with contextlib.suppress(discord.HTTPException):
            await config.thread.send(
                f"\u23f3 Waiting for a free session slot\u2026 "
                f"({_max_concurrent} max sessions running)"
            )
    if sem is not None:
        await sem.acquire()

    try:
        async for event in runner.run(config.prompt, session_id=config.session_id):
            if processor.should_drain and not event.is_complete:
                continue
            await processor.process(event)
    except Exception as exc:
        logger.exception("Error running Claude CLI for thread %d", config.thread.id)
        with contextlib.suppress(Exception):
            detail = f"{type(exc).__name__}: {exc}"
            await config.thread.send(
                embed=error_embed(f"An unexpected error occurred.\n```\n{detail}\n```")
            )
        if config.status:
            with contextlib.suppress(Exception):
                await config.status.set_error()
        return processor.session_id
    finally:
        if sem is not None:
            sem.release()
        await processor.finalize()
        if config.registry is not None:
            config.registry.unregister(config.thread.id)
        if config.worktree_manager is not None:
            await _cleanup_session_worktree(config)

    # After compact_boundary, rerun with a guardrail to prevent Claude from
    # auto-executing "pending tasks" from the compacted context summary.
    if processor.compact_occurred:
        session_id = processor.session_id or config.session_id
        logger.info(
            "Compact detected for session %s — rerunning with post-compact guardrail", session_id
        )
        guardrail_config = replace(config, session_id=session_id, post_compact_rerun=True)
        return await run_claude_with_config(guardrail_config)

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
    thread: discord.Thread | discord.TextChannel,
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
