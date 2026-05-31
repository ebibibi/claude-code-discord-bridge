"""Tests for hook event parsing and processing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_code_core.parser import parse_line
from claude_code_core.types import HookEvent, MessageType, StreamEvent


class TestHookProgressParsing:
    """Tests for hook_progress events in progress messages."""

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
        assert event.hook_event.hook_name == "Stop:*"
        assert event.hook_event.command == "~/.claude/hooks/check-uncommitted.sh"

    def test_hook_progress_with_status_message(self) -> None:
        line = json.dumps(
            {
                "type": "progress",
                "data": {
                    "type": "hook_progress",
                    "hookEvent": "Stop",
                    "hookName": "Stop:*",
                    "command": "evaluate-session.sh",
                    "statusMessage": "Evaluating session patterns...",
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event is not None
        assert event.hook_event.status_message == "Evaluating session patterns..."

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

    def test_progress_without_data(self) -> None:
        line = json.dumps({"type": "progress"})
        event = parse_line(line)
        assert event is not None
        assert event.hook_event is None


class TestStopHookSummaryParsing:
    """Tests for stop_hook_summary system events."""

    def test_stop_hook_summary_with_output(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hasOutput": True,
                "hookEvent": "Stop",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM
        assert event.stop_hook_has_output is True

    def test_stop_hook_summary_without_output(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hasOutput": False,
                "hookEvent": "Stop",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.stop_hook_has_output is False

    def test_stop_hook_summary_default_no_output(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "stop_hook_summary",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.stop_hook_has_output is False


class TestHookLifecycleParsing:
    """Tests for hook_execution_start and hook_execution_complete system events."""

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
        assert event.message_type == MessageType.SYSTEM
        assert event.hook_event is not None
        assert event.hook_event.hook_event_name == "Stop"
        assert event.hook_event.lifecycle == "start"
        assert event.hook_event.num_hooks == 4

    def test_hook_execution_complete(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_execution_complete",
                "hook_event": "Stop",
                "hook_name": "Stop",
                "num_hooks": "4",
                "num_success": "3",
                "num_blocking": "0",
                "total_duration_ms": "1234",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.hook_event is not None
        assert event.hook_event.lifecycle == "complete"
        assert event.hook_event.num_hooks == 4
        assert event.hook_event.duration_ms == 1234


class TestRunnerIncludeHookEvents:
    """Tests for --include-hook-events flag in runner."""

    def test_include_hook_events_in_args(self) -> None:
        from claude_code_core.runner import ClaudeRunner

        runner = ClaudeRunner()
        args = runner._build_args("hello", None)
        assert "--include-hook-events" in args

    def test_include_hook_events_with_session_resume(self) -> None:
        from claude_code_core.runner import ClaudeRunner

        runner = ClaudeRunner()
        args = runner._build_args("hello", "abc-123")
        assert "--include-hook-events" in args

    def test_clone_preserves_include_hook_events(self) -> None:
        from claude_code_core.runner import ClaudeRunner

        runner = ClaudeRunner()
        cloned = runner.clone()
        args = cloned._build_args("hello", None)
        assert "--include-hook-events" in args


def _make_config(thread: MagicMock, runner: MagicMock, **kwargs):
    from claude_discord.cogs.run_config import RunConfig

    return RunConfig(thread=thread, runner=runner, prompt="test", **kwargs)


class TestEventProcessorHookEvents:
    """Tests for EventProcessor handling of hook events."""

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

    @pytest.mark.asyncio
    async def test_hook_progress_without_status_is_noop(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner)
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

    @pytest.mark.asyncio
    async def test_hook_lifecycle_start_sends_message(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(
                hook_event_name="Stop",
                lifecycle="start",
                num_hooks=4,
            ),
        )
        await proc.process(event)
        thread.send.assert_awaited()
        sent_text = thread.send.call_args[0][0]
        assert "Stop" in sent_text
        assert "4" in sent_text

    @pytest.mark.asyncio
    async def test_hook_lifecycle_start_skipped_in_chat_only(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        from claude_discord.cogs.event_processor import EventProcessor

        config = _make_config(thread, runner, chat_only=True)
        proc = EventProcessor(config)

        event = StreamEvent(
            message_type=MessageType.SYSTEM,
            hook_event=HookEvent(
                hook_event_name="Stop",
                lifecycle="start",
                num_hooks=4,
            ),
        )
        await proc.process(event)
        thread.send.assert_not_awaited()
