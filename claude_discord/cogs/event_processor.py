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
from pathlib import Path

import discord

from ..claude.types import AskQuestion, MessageType, SessionState, StreamEvent
from ..discord_ui.chunker import chunk_message
from ..discord_ui.elicitation_view import ElicitationFormView, ElicitationUrlView
from ..discord_ui.embeds import (
    elicitation_embed,
    permission_embed,
    plan_embed,
    redacted_thinking_embed,
    session_start_embed,
    thinking_embed,
    todo_embed,
    tool_result_embed,
    tool_result_preview_embed,
    tool_use_embed,
)
from ..discord_ui.file_sender import send_files
from ..discord_ui.permission_view import PermissionView
from ..discord_ui.plan_view import PlanApprovalView
from ..discord_ui.streaming_manager import StreamingMessageManager
from ..discord_ui.tool_timer import LiveToolTimer
from .run_config import RunConfig

logger = logging.getLogger(__name__)

# Marker file written by Claude when the user asks to receive specific files.
_ATTACHMENT_MARKER = ".ccdb-attachments"


async def _send_attachment_requests(
    thread: object,
    working_dir: str | None,
) -> None:
    """Read .ccdb-attachments and send listed files to Discord.

    If the marker file does not exist or is empty, this is a no-op.
    The marker file is deleted after sending so it does not persist into
    future sessions.  Any error (missing file, Discord API failure, etc.)
    is suppressed — file attachment is non-fatal.
    """
    if not working_dir:
        logger.debug("_send_attachment_requests: no working_dir, skipping")
        return
    marker = Path(working_dir) / _ATTACHMENT_MARKER
    if not marker.exists():
        logger.debug("_send_attachment_requests: %s not found, skipping", marker)
        return
    logger.info("_send_attachment_requests: found %s", marker)
    with contextlib.suppress(OSError):
        paths = [p.strip() for p in marker.read_text(encoding="utf-8").splitlines() if p.strip()]
        marker.unlink(missing_ok=True)
        if paths:
            # Resolve relative paths against working_dir.  Claude is instructed to
            # write absolute paths, but may write a bare filename.  Resolving here
            # ensures the file is found even when the bot process has a different cwd.
            wd = Path(working_dir)
            abs_paths = [raw if Path(raw).is_absolute() else str(wd / raw) for raw in paths]
            logger.info(
                "_send_attachment_requests: sending %d file(s): %s",
                len(abs_paths),
                abs_paths,
            )
            await send_files(thread, abs_paths, working_dir)  # type: ignore[arg-type]


# Max characters for tool result display.
# Sized to show ~30 lines of typical output (100 chars/line × 30 = 3000).
# The embed description limit is 4096, so this leaves room for code block markers.
_TOOL_RESULT_MAX_CHARS = 3000
# Lines of output shown inline before the "Expand ▼" button appears.
# 1 means single-line results are shown flat; 2+ lines get a collapse button.
_COLLAPSED_LINES = 1


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
        elif event.message_type == MessageType.PROGRESS:
            await self._on_progress(event)

        elif event.message_type == MessageType.RATE_LIMIT_EVENT:
            await self._on_rate_limit_event(event)

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
        """Handle SYSTEM events — capture session_id, post start embed, compact notification."""
        # Context compaction notification
        if event.is_compact and self._config.status:
            await self._config.status.set_compact()
            pre = event.compact_pre_tokens
            trigger = event.compact_trigger or "auto"
            label = f"\U0001f5dc\ufe0f Context compacted ({trigger})"
            if pre:
                label += f" \u2014 was {pre:,} tokens"
            with contextlib.suppress(discord.HTTPException):
                await self._config.thread.send(f"-# {label}")

        # Permission request — show Allow/Deny buttons
        if event.permission_request is not None:
            await self._handle_permission_request(event)
            return

        # MCP elicitation — show form or URL button
        if event.elicitation is not None:
            await self._handle_elicitation(event)
            return

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

        # TodoWrite — post or edit the live todo progress embed.
        if event.todo_list is not None:
            await self._handle_todo_write(event)

        # ExitPlanMode — show plan embed with Approve/Cancel buttons.
        if event.is_plan_approval and not event.is_partial:
            await self._handle_plan_approval(event)

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
        if tool_msg is None:
            return

        title = tool_msg.embeds[0].title or ""
        if event.tool_result_content:
            truncated = _truncate_result(event.tool_result_content)
            if len(truncated.split("\n")) > _COLLAPSED_LINES:
                from ..discord_ui.views import ToolResultView

                embed = tool_result_preview_embed(title, truncated)
                view = ToolResultView(title, truncated)
                try:
                    await tool_msg.edit(embed=embed, view=view)
                except Exception:
                    logger.warning("Failed to update tool result embed", exc_info=True)
            else:
                try:
                    await tool_msg.edit(embed=tool_result_embed(title, truncated))
                except Exception:
                    logger.warning("Failed to update tool result embed", exc_info=True)
        else:
            # Tool completed with no output — remove the in-progress indicator.
            try:
                await tool_msg.edit(embed=tool_result_embed(title, ""))
            except Exception:
                logger.warning("Failed to clear tool in-progress indicator", exc_info=True)

    async def _on_progress(self, event: StreamEvent) -> None:
        """Handle PROGRESS events — reset stall timer (compact in progress)."""
        if self._config.status:
            self._config.status._reset_stall_timer()

    async def _on_rate_limit_event(self, event: StreamEvent) -> None:
        """Handle RATE_LIMIT_EVENT — persist latest rate limit info to usage_stats."""
        if self._config.usage_repo is None or event.rate_limit_info is None:
            return
        await self._config.usage_repo.upsert(event.rate_limit_info)

    async def _on_complete(self, event: StreamEvent) -> None:
        """Handle RESULT events — finalize streaming, post summary embed."""
        import asyncio

        from ..discord_ui.embeds import (
            session_complete_embed,
        )
        from ..discord_ui.streaming_manager import StreamingMessageManager
        from ._run_helper import _make_error_embed

        # Finalize any in-progress streaming message.
        # Capture the URL before sending session_complete_embed (which would
        # become last_message_id and hide Claude's actual reply).
        last_assistant_url: str | None = None
        last_assistant_text: str = self._state.accumulated_text

        if self._streamer.has_content:
            await self._streamer.finalize()
            self._assistant_text_sent = True
            if self._streamer._current_message is not None:
                last_assistant_url = self._streamer._current_message.jump_url

        if event.error:
            await self._config.thread.send(embed=_make_error_embed(event.error))
            if self._config.status:
                await self._config.status.set_error()
        else:
            # Post final result text only if no assistant text was already sent.
            response_text = event.text
            if response_text and not self._assistant_text_sent:
                last_sent: discord.Message | None = None
                for chunk in chunk_message(response_text):
                    last_sent = await self._config.thread.send(chunk)
                if last_sent is not None:
                    last_assistant_url = last_sent.jump_url
                last_assistant_text = response_text

            # Send files listed in the .ccdb-attachments marker file, if present.
            await _send_attachment_requests(
                self._config.thread,
                self._config.runner.working_dir,
            )

            await self._config.thread.send(
                embed=session_complete_embed(
                    event.cost_usd,
                    event.duration_ms,
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_read_tokens,
                    event.context_window,
                    event.cache_creation_tokens,
                )
            )
            if self._config.status:
                await self._config.status.set_done()

            # Schedule inbox classification as a background task (non-blocking).
            # Only runs when inbox_repo is wired in (THREAD_INBOX_ENABLED=true).
            if self._config.inbox_repo is not None and last_assistant_text:
                asyncio.create_task(
                    _classify_and_update_inbox(
                        thread_id=self._config.thread.id,
                        last_text=last_assistant_text,
                        last_message_url=last_assistant_url,
                        inbox_repo=self._config.inbox_repo,
                        dashboard=self._config.inbox_dashboard,
                        claude_command=self._config.claude_command,
                    ),
                    name=f"inbox-classify-{self._config.thread.id}",
                )

        if event.session_id:
            if self._config.repo:
                await self._config.repo.save(self._config.thread.id, event.session_id)
            self._state.session_id = event.session_id

        # Persist context window stats (requires repo + context_window in event).
        if self._config.repo and event.context_window is not None:
            context_used = (
                (event.input_tokens or 0)
                + (event.cache_read_tokens or 0)
                + (event.cache_creation_tokens or 0)
            )
            await self._config.repo.update_context_stats(
                thread_id=self._config.thread.id,
                context_window=event.context_window,
                context_used=context_used,
            )

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

        self._state.tool_use_count += 1

        if self._config.status:
            await self._config.status.set_tool(event.tool_use.category)

        embed = tool_use_embed(event.tool_use, in_progress=True)
        try:
            msg = await self._config.thread.send(embed=embed)
        except Exception:
            logger.debug("Failed to send tool embed", exc_info=True)
            return
        self._state.active_tools[event.tool_use.tool_id] = msg

        timer = LiveToolTimer(msg, event.tool_use)
        self._state.active_timers[event.tool_use.tool_id] = timer.start()

        await self._bump_stop()

    async def _handle_plan_approval(self, event: StreamEvent) -> None:
        """Post the plan embed with Approve/Cancel buttons (ExitPlanMode)."""
        plan_text = event.text or ""
        embed = plan_embed(plan_text)
        # ExitPlanMode does not carry a request_id in the current CLI protocol;
        # we use the session_id as a stable identifier for the inject payload.
        request_id = self._state.session_id or "plan"
        view = PlanApprovalView(self._config.runner, request_id)
        await self._config.thread.send(embed=embed, view=view)
        logger.info("Plan approval prompt posted (session=%s)", request_id)

    async def _handle_permission_request(self, event: StreamEvent) -> None:
        """Post permission embed with Allow/Deny buttons."""
        assert event.permission_request is not None
        embed = permission_embed(event.permission_request)
        view = PermissionView(self._config.runner, event.permission_request)
        await self._config.thread.send(embed=embed, view=view)
        logger.info(
            "Permission request posted: %s (request_id=%s)",
            event.permission_request.tool_name,
            event.permission_request.request_id,
        )

    async def _handle_elicitation(self, event: StreamEvent) -> None:
        """Post elicitation embed with appropriate UI (URL button or form Modal button)."""
        assert event.elicitation is not None
        req = event.elicitation
        embed = elicitation_embed(req)
        if req.mode == "url-mode":
            view = ElicitationUrlView(self._config.runner, req)
        else:
            view = ElicitationFormView(self._config.runner, req)
        await self._config.thread.send(embed=embed, view=view)
        logger.info(
            "Elicitation posted: %s (%s, request_id=%s)",
            req.server_name,
            req.mode,
            req.request_id,
        )

    async def _handle_todo_write(self, event: StreamEvent) -> None:
        """Always repost the todo embed at the bottom of the thread.

        Each TodoWrite call deletes the previous embed (if any) and posts a
        fresh message so the task list stays visible as the conversation grows.
        """
        assert event.todo_list is not None

        embed = todo_embed(event.todo_list)

        # Delete the previous todo message so we can repost at the bottom.
        if self._state.todo_message is not None:
            try:
                await self._state.todo_message.delete()
            except Exception:
                logger.warning("Failed to delete previous todo embed", exc_info=True)
            self._state.todo_message = None

        # Post a fresh message at the bottom of the thread.
        try:
            self._state.todo_message = await self._config.thread.send(embed=embed)
        except Exception:
            logger.warning(
                "Failed to post todo embed; will retry on next TodoWrite call", exc_info=True
            )

    async def _bump_stop(self) -> None:
        """Move the Stop button to the bottom of the thread if configured."""
        if self._config.stop_view:
            await self._config.stop_view.bump(self._config.thread)


# ---------------------------------------------------------------------------
# Inbox classification helper (module-level so it can be unit-tested)
# ---------------------------------------------------------------------------


async def _classify_and_update_inbox(
    thread_id: int,
    last_text: str,
    last_message_url: str | None,
    inbox_repo: object,
    dashboard: object | None,
    claude_command: str,
) -> None:
    """Classify the session's final message and persist the inbox entry.

    Runs as a background asyncio task so it does not block the main flow.
    Type annotations use ``object`` to avoid a circular import; the actual
    types are ThreadInboxRepository and ThreadStatusDashboard.
    """
    from ..database.inbox_repo import ThreadInboxRepository
    from ..discord_ui.inbox_classifier import classify
    from ..discord_ui.thread_dashboard import ThreadStatusDashboard

    assert isinstance(inbox_repo, ThreadInboxRepository)

    try:
        result = await classify(last_text, claude_command=claude_command)
        logger.debug("inbox classify thread_id=%d result=%s", thread_id, result)

        if result == "done":
            # Proactively remove from inbox — no action needed
            await inbox_repo.remove(thread_id)
        else:
            confidence = "high" if result == "waiting" else "low"
            await inbox_repo.upsert(
                thread_id=thread_id,
                status=result,  # type: ignore[arg-type]
                confidence=confidence,
                last_message_url=last_message_url,
            )

        if isinstance(dashboard, ThreadStatusDashboard):
            await dashboard.refresh_inbox(inbox_repo)

    except Exception:
        logger.warning("inbox classify task failed for thread_id=%d", thread_id, exc_info=True)
