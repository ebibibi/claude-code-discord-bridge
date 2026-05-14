"""Tests for CodexRunner — OpenAI Codex CLI backend."""

from __future__ import annotations

import json

import pytest

from claude_code_core.backend import SessionBackend
from claude_code_core.codex_runner import CodexRunner, parse_codex_line
from claude_code_core.types import MessageType


class TestCodexRunnerIsBackend:
    """CodexRunner must satisfy the SessionBackend protocol."""

    def test_is_session_backend(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        assert isinstance(runner, SessionBackend)


class TestCodexRunnerBuildArgs:
    """Tests for _build_args() — Codex CLI flag assembly."""

    def test_basic_args(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        args = runner._build_args("hello", session_id=None)
        assert args[0] == "codex"
        assert "exec" in args
        assert "--json" in args
        assert "--model" in args or "-m" in args
        assert "o4-mini" in args

    def test_resume_session(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        args = runner._build_args("hello", session_id="0199a213-81c0-7800-8aa1-bbab2a035a53")
        assert "resume" in args
        assert "0199a213-81c0-7800-8aa1-bbab2a035a53" in args

    def test_approval_mode_mapping(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini", permission_mode="acceptEdits")
        args = runner._build_args("hello", session_id=None)
        assert any(a in args for a in ["--ask-for-approval", "-a"])

    def test_dangerously_skip_permissions(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini", dangerously_skip_permissions=True)
        args = runner._build_args("hello", session_id=None)
        assert "--yolo" in args or "--dangerously-bypass-approvals-and-sandbox" in args

    def test_working_dir_flag(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini", working_dir="/tmp/work")
        args = runner._build_args("hello", session_id=None)
        assert "--cd" in args or "-C" in args
        assert "/tmp/work" in args

    def test_prompt_is_last_arg(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        args = runner._build_args("hello world", session_id=None)
        assert args[-1] == "hello world"

    def test_session_id_validation(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        with pytest.raises(ValueError, match="Invalid session_id"):
            runner._build_args("hello", session_id="'; DROP TABLE --")


class TestCodexRunnerClone:
    """Tests for clone() — creating a new runner with overrides."""

    def test_clone_preserves_config(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini", working_dir="/tmp")
        cloned = runner.clone()
        assert isinstance(cloned, CodexRunner)
        assert cloned.model == "o4-mini"
        assert cloned.working_dir == "/tmp"

    def test_clone_overrides_model(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        cloned = runner.clone(model="gpt-5.4")
        assert cloned.model == "gpt-5.4"

    def test_clone_overrides_working_dir(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini", working_dir="/old")
        cloned = runner.clone(working_dir="/new")
        assert cloned.working_dir == "/new"

    def test_clone_returns_codex_runner_not_claude(self) -> None:
        runner = CodexRunner(command="codex", model="o4-mini")
        cloned = runner.clone(model="gpt-5.4")
        assert type(cloned) is CodexRunner


class TestParseCodexLine:
    """Tests for parse_codex_line() — Codex JSONL → StreamEvent."""

    def test_thread_started(self) -> None:
        line = json.dumps({"type": "thread.started", "thread_id": "abc-123"})
        event = parse_codex_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM
        assert event.session_id == "abc-123"

    def test_item_completed_agent_message(self) -> None:
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "agent_message",
                    "text": "Hello, world!",
                },
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert event.message_type == MessageType.ASSISTANT
        assert event.text == "Hello, world!"

    def test_item_started_command_execution(self) -> None:
        line = json.dumps(
            {
                "type": "item.started",
                "item": {
                    "id": "item_2",
                    "type": "command_execution",
                    "command": "ls -la",
                    "status": "in_progress",
                },
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert event.tool_use is not None
        assert event.tool_use.tool_name == "Bash"
        assert event.tool_use.tool_input.get("command") == "ls -la"

    def test_turn_completed_with_usage(self) -> None:
        line = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cached_input_tokens": 500,
                    "reasoning_output_tokens": 50,
                },
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert event.input_tokens == 1000
        assert event.output_tokens == 200
        assert event.cache_read_tokens == 500

    def test_item_completed_command_execution(self) -> None:
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_2",
                    "type": "command_execution",
                    "command": "ls -la",
                    "output": "total 42\ndrwxr-xr-x ...",
                },
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert event.tool_result_content is not None

    def test_invalid_json_returns_none(self) -> None:
        event = parse_codex_line("not valid json")
        assert event is None

    def test_empty_line_returns_none(self) -> None:
        event = parse_codex_line("")
        assert event is None

    def test_item_completed_file_changes(self) -> None:
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_3",
                    "type": "file_changes",
                    "text": "Modified src/main.py",
                },
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert event.tool_use is not None
        assert event.tool_use.tool_name == "Edit"

    def test_turn_started(self) -> None:
        line = json.dumps({"type": "turn.started"})
        event = parse_codex_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM

    def test_error_event(self) -> None:
        line = json.dumps({"type": "error", "message": "something broke"})
        event = parse_codex_line(line)
        assert event is not None
        assert event.error is not None
        assert event.is_complete is True
