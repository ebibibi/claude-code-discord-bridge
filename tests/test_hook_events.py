"""Tests for hook event parsing and processing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_code_core.parser import parse_line
from claude_code_core.types import HookEvent, MessageType, StreamEvent

# ---------------------------------------------------------------------------
# Parser: hook_started / hook_response / hook_progress (system events)
# ---------------------------------------------------------------------------


class TestHookStartedParsing:
    """Tests for hook_started system events (per-hook start)."""

    def test_hook_started_parsed(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_started",
                "hook_id": "abc-123",
                "hook_name": "Stop",
                "hook_event": "Stop",
                "session_id": "sess-1",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM
        assert event.hook_event is not None
        assert event.hook_event.hook_event_name == "Stop"
        assert event.hook_event.hook_name == "Stop"
        assert event.hook_event.lifecycle == "started"

    def test_hook_started_session_start(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_started",
                "hook_name": "SessionStart:startup",
                "hook_event": "SessionStart",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event.hook_event_name == "SessionStart"


class TestHookResponseParsing:
    """Tests for hook_response system events (per-hook completion with output)."""

    def test_hook_response_with_stderr(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_response",
                "hook_id": "abc-123",
                "hook_name": "Stop",
                "hook_event": "Stop",
                "output": "⚠️ [未コミット検知] ...",
                "stdout": "",
                "stderr": "⚠️ [未コミット検知] 以下のリポジトリに未コミットの変更があります:",
                "exit_code": 0,
                "outcome": "success",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event is not None
        assert event.hook_event.lifecycle == "response"
        assert "未コミット検知" in event.hook_event.stderr
        assert event.hook_event.outcome == "success"
        assert event.hook_event.exit_code == 0

    def test_hook_response_no_stderr(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_response",
                "hook_name": "Stop",
                "hook_event": "Stop",
                "output": "",
                "stdout": "",
                "stderr": "",
                "exit_code": 0,
                "outcome": "success",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event.stderr == ""
        assert event.hook_event.outcome == "success"

    def test_hook_response_error_outcome(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_response",
                "hook_name": "Stop",
                "hook_event": "Stop",
                "stderr": "hook script failed",
                "exit_code": 1,
                "outcome": "error",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event.outcome == "error"
        assert event.hook_event.exit_code == 1


class TestHookProgressSystemParsing:
    """Tests for hook_progress as system events (async hooks)."""

    def test_hook_progress_system_event(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_progress",
                "hook_name": "SessionStart:startup",
                "hook_event": "SessionStart",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM
        assert event.hook_event is not None
        assert event.hook_event.lifecycle == "progress"


# ---------------------------------------------------------------------------
# Parser: hook_progress in progress messages (kept for compatibility)
# ---------------------------------------------------------------------------


class TestHookProgressInProgressMessage:
    """Tests for hook_progress data inside progress-type messages."""

    def test_hook_progress_parsed(self) -> None:
        line = json.dumps(
            {
                "type": "progress",
                "data": {
                    "type": "hook_progress",
                    "hookEvent": "Stop",
                    "hookName": "Stop:*",
                    "command": "~/.claude/hooks/check-uncommitted.sh",
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.PROGRESS
        assert event.hook_event is not None
        assert event.hook_event.hook_event_name == "Stop"

    def test_non_hook_progress_has_no_hook_event(self) -> None:
        line = json.dumps(
            {
                "type": "progress",
                "data": {"message": {"type": "assistant"}},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event is None


# ---------------------------------------------------------------------------
# Parser: stop_hook_summary
# ---------------------------------------------------------------------------


class TestStopHookSummaryParsing:
    def test_stop_hook_summary_with_output(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hasOutput": True,
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.stop_hook_has_output is True

    def test_stop_hook_summary_without_output(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hasOutput": False,
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.stop_hook_has_output is False


# ---------------------------------------------------------------------------
# Parser: legacy batch events (kept for backward compat)
# ---------------------------------------------------------------------------


class TestLegacyHookLifecycleParsing:
    def test_hook_execution_start(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_execution_start",
                "hook_event": "Stop",
                "hook_name": "Stop",
                "num_hooks": "4",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event is not None
        assert event.hook_event.lifecycle == "start"
        assert event.hook_event.num_hooks == 4


# ---------------------------------------------------------------------------
# Runner: --include-hook-events
# ---------------------------------------------------------------------------


class TestRunnerIncludeHookEvents:
    def test_include_hook_events_in_args(self) -> None:
        from claude_code_core.runner import ClaudeRunner

        runner = ClaudeRunner()
        args = runner._build_args("hello", None)
        assert "--include-hook-events" in args

    def test_clone_preserves_include_hook_events(self) -> None:
        from claude_code_core.runner import ClaudeRunner

        runner = ClaudeRunner()
        cloned = runner.clone()
        args = cloned._build_args("hello", None)
        assert "--include-hook-events" in args


# ---------------------------------------------------------------------------
# EventProcessor: hook event handling
# ---------------------------------------------------------------------------


def _make_config(thread: MagicMock, runner: MagicMock, **kwargs):
    from claude_discord.cogs.run_config import RunConfig

    return RunConfig(thread=thread, runner=runner, prompt="test", **kwargs)


class TestEventProcessorHookEvents:
    @pytest.mark.asyncio
    async def test_hook_started_sets_status(self, thread: MagicMock, runner: MagicMock) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        status = MagicMock()
        status.set_hook = AsyncMock()
        config = _make_config(thread, runner, status=status)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(hook_event_name="Stop", lifecycle="started"),
        )
        await proc.process(event)
        status.set_hook.assert_awaited_once_with("Stop")

    @pytest.mark.asyncio
    async def test_hook_response_stderr_shown_in_discord(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(
                hook_event_name="Stop",
                lifecycle="response",
                stderr="⚠️ [未コミット検知] repo-a: M file.py",
                outcome="success",
                exit_code=0,
            ),
        )
        await proc.process(event)
        thread.send.assert_awaited_once()
        sent = thread.send.call_args[0][0]
        assert "未コミット検知" in sent

    @pytest.mark.asyncio
    async def test_hook_response_empty_stderr_no_message(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(
                hook_event_name="Stop",
                lifecycle="response",
                stderr="",
                outcome="success",
            ),
        )
        await proc.process(event)
        thread.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hook_response_stderr_skipped_in_chat_only(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner, chat_only=True)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(
                hook_event_name="Stop",
                lifecycle="response",
                stderr="⚠️ warning message",
                outcome="success",
            ),
        )
        await proc.process(event)
        thread.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hook_response_stderr_truncated(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner)
        proc = EventProcessor(config)

        long_stderr = "\n".join(f"line {i}" for i in range(20))
        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(
                hook_event_name="Stop",
                lifecycle="response",
                stderr=long_stderr,
                outcome="success",
            ),
        )
        await proc.process(event)
        sent = thread.send.call_args[0][0]
        assert "+14 lines" in sent

    @pytest.mark.asyncio
    async def test_hook_progress_sets_status(self, thread: MagicMock, runner: MagicMock) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        status = MagicMock()
        status.set_hook = AsyncMock()
        config = _make_config(thread, runner, status=status)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.PROGRESS,
            hook_event=HookEvent(
                hook_event_name="Stop",
                hook_name="Stop:*",
                command="check-uncommitted.sh",
            ),
        )
        await proc.process(event)
        status.set_hook.assert_awaited_once_with("Stop")
