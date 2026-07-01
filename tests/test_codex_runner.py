"""Tests for CodexRunner — OpenAI Codex CLI backend."""

from __future__ import annotations

import json

import pytest

from claude_code_core.backend import SessionBackend
from claude_code_core.codex_runner import CodexRunner, parse_codex_line
from claude_code_core.types import MessageType


class _FakeStream:
    def __init__(self, lines: list[bytes] | None = None, read_data: bytes = b"") -> None:
        self._lines = list(lines or [])
        self._read_data = read_data

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self) -> bytes:
        return self._read_data


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout_lines: list[bytes] | None = None,
        stderr: bytes = b"",
        returncode: int = 0,
        pid: int = 12345,
    ) -> None:
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream(read_data=stderr)
        self.returncode = returncode
        self.pid = pid

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


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

    def test_no_model_omits_model_flag(self) -> None:
        # model=None (the new default) means: defer to the Codex CLI's own
        # config.toml default — never pass --model.
        runner = CodexRunner(command="codex")
        assert runner.model is None
        args = runner._build_args("hello", session_id=None)
        assert "--model" not in args
        assert "-m" not in args

    def test_empty_model_omits_model_flag(self) -> None:
        runner = CodexRunner(command="codex", model="")
        args = runner._build_args("hello", session_id=None)
        assert "--model" not in args

    def test_effort_injects_reasoning_config(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.5", effort="high")
        args = runner._build_args("hello", session_id=None)
        assert "-c" in args
        assert "model_reasoning_effort=high" in args

    def test_no_effort_omits_reasoning_config(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.5")
        args = runner._build_args("hello", session_id=None)
        assert not any(a.startswith("model_reasoning_effort=") for a in args)

    def test_invalid_effort_raises(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.5", effort="bogus")
        with pytest.raises(ValueError, match="Invalid Codex effort"):
            runner._build_args("hello", session_id=None)


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

    def test_clone_preserves_effort(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.5", effort="xhigh")
        cloned = runner.clone()
        assert cloned.effort == "xhigh"

    def test_clone_overrides_effort(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.5", effort="high")
        cloned = runner.clone(effort="low")
        assert cloned.effort == "low"


class TestCodexRunnerRun:
    @pytest.mark.asyncio
    async def test_resume_missing_rollout_falls_back_to_new_session(self, monkeypatch) -> None:
        stale_session = "13f2eb43-93cf-4df6-86d0-a20c035cc26e"
        started_line = json.dumps(
            {"type": "thread.started", "thread_id": "019f-new-session"}
        ).encode()
        completed_line = json.dumps({"type": "turn.completed", "usage": {}}).encode()
        processes = [
            _FakeProcess(
                stderr=(
                    b"Error: thread/resume: thread/resume failed: "
                    b"no rollout found for thread id 13f2eb43-93cf-4df6-86d0-a20c035cc26e"
                ),
                returncode=1,
                pid=100,
            ),
            _FakeProcess(
                stdout_lines=[started_line + b"\n", completed_line + b"\n"],
                returncode=0,
                pid=101,
            ),
        ]
        calls: list[tuple[str, ...]] = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            calls.append(args)
            return processes.pop(0)

        monkeypatch.setattr(
            "claude_code_core.codex_runner.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )
        runner = CodexRunner(command="codex", working_dir="/work")

        events = [event async for event in runner.run("hello", session_id=stale_session)]

        assert len(calls) == 2
        assert calls[0][:3] == ("codex", "exec", "resume")
        assert stale_session in calls[0]
        assert "resume" not in calls[1]
        assert "--cd" in calls[1]
        assert "/work" in calls[1]
        assert [event.error for event in events if event.error] == []
        assert events[0].session_id == "019f-new-session"

    @pytest.mark.asyncio
    async def test_non_rollout_resume_error_is_reported(self, monkeypatch) -> None:
        process = _FakeProcess(stderr=b"permission denied", returncode=1)

        async def fake_create_subprocess_exec(*args, **kwargs):
            return process

        monkeypatch.setattr(
            "claude_code_core.codex_runner.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )
        runner = CodexRunner(command="codex")

        events = [
            event
            async for event in runner.run(
                "hello",
                session_id="019e29a0-d5b0-71f0-bdc0-46f09a06fdaf",
            )
        ]

        assert len(events) == 1
        assert events[0].error is not None
        assert "CLI exited with code 1" in events[0].error


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

    def test_command_execution_completion_routes_as_tool_result(self) -> None:
        """The completion must be a USER event so EventProcessor cancels the
        live timer via _on_tool_result. If it stays ASSISTANT, the timer runs
        forever and the embed is stuck on "Running ... Ns elapsed"."""
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_2",
                    "type": "command_execution",
                    "command": "ls -la",
                    "output": "total 42",
                },
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert event.message_type == MessageType.USER
        assert event.tool_result_id == "item_2"

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

    def test_file_changes_is_atomic_and_gets_synthetic_completion(self) -> None:
        """file_changes arrives as a single item.completed with no item.started.
        It opens a tool embed + live timer, so a synthetic tool result must be
        paired with it to stop the timer."""
        from claude_code_core.codex_runner import _atomic_tool_completion

        line = json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_3", "type": "file_changes", "text": "Modified main.py"},
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        completion = _atomic_tool_completion(event)
        assert completion is not None
        assert completion.message_type == MessageType.USER
        assert completion.tool_result_id == "item_3"

    def test_command_execution_start_is_not_atomic(self) -> None:
        """A command_execution start has its own completion event, so it must
        NOT receive a synthetic completion (that would double-cancel)."""
        from claude_code_core.codex_runner import _atomic_tool_completion

        line = json.dumps(
            {
                "type": "item.started",
                "item": {"id": "item_2", "type": "command_execution", "command": "ls"},
            }
        )
        event = parse_codex_line(line)
        assert event is not None
        assert _atomic_tool_completion(event) is None

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


class TestCodexRunnerArgvStructure:
    """Strict structural tests — verify args match codex CLI's actual grammar.

    Codex CLI v0.124 grammar (verified against ``codex exec --help`` /
    ``codex exec resume --help``):

        codex exec [OPTIONS] [PROMPT]
        codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]

    ``exec`` accepts: ``--json``, ``--model``, ``--ask-for-approval``,
    ``--dangerously-bypass-approvals-and-sandbox``, ``--cd``.
    ``exec resume`` accepts the same flags EXCEPT ``--cd`` (causes exit code 2).
    The resume positional args come AFTER all flags, with SESSION_ID before PROMPT.

    These tests guard against regressions like the one that shipped briefly
    in 3.0.0 where resume was invoked as ``codex resume <id> --json …`` —
    a structure codex rejects with ``error: unexpected argument '--json'
    found``.
    """

    def test_new_session_starts_with_exec(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.4")
        args = runner._build_args("prompt", session_id=None)
        # First positional must be the command, second must be 'exec',
        # and 'resume' must NOT appear when starting a new session.
        assert args[0] == "codex"
        assert args[1] == "exec"
        assert "resume" not in args

    def test_resume_starts_with_exec_resume(self) -> None:
        sid = "019e29a0-d5b0-71f0-bdc0-46f09a06fdaf"
        runner = CodexRunner(command="codex", model="gpt-5.4")
        args = runner._build_args("prompt", session_id=sid)
        # The first three tokens must be exactly: codex exec resume
        assert args[:3] == ["codex", "exec", "resume"], (
            f"Codex resume must be invoked as `codex exec resume`, got: {args[:3]!r}"
        )

    def test_resume_flags_precede_session_id(self) -> None:
        sid = "019e29a0-d5b0-71f0-bdc0-46f09a06fdaf"
        runner = CodexRunner(
            command="codex",
            model="gpt-5.4",
            permission_mode="acceptEdits",
            working_dir="/work",
        )
        args = runner._build_args("hello", session_id=sid)
        sid_idx = args.index(sid)
        # --json, --model, --ask-for-approval must all come before SESSION_ID.
        # NOTE: --cd is NOT supported by `codex exec resume` (only by `codex exec`).
        for flag in ("--json", "--model", "--ask-for-approval"):
            assert flag in args, f"{flag} missing from resume args"
            assert args.index(flag) < sid_idx, (
                f"{flag} should appear before SESSION_ID in codex exec resume"
            )

    def test_cd_flag_not_passed_on_resume(self) -> None:
        """codex exec resume does not accept --cd; must be omitted to avoid exit code 2."""
        sid = "019e29a0-d5b0-71f0-bdc0-46f09a06fdaf"
        runner = CodexRunner(command="codex", model="gpt-5.4", working_dir="/work")
        args = runner._build_args("hello", session_id=sid)
        assert "--cd" not in args, (
            "`codex exec resume` does not support --cd; passing it causes exit code 2"
        )

    def test_cd_flag_passed_on_new_session(self) -> None:
        """--cd must still be passed for new sessions."""
        runner = CodexRunner(command="codex", model="gpt-5.4", working_dir="/work")
        args = runner._build_args("hello", session_id=None)
        assert "--cd" in args
        assert "/work" in args

    def test_resume_session_id_before_prompt(self) -> None:
        sid = "019e29a0-d5b0-71f0-bdc0-46f09a06fdaf"
        runner = CodexRunner(command="codex", model="gpt-5.4")
        args = runner._build_args("hello-prompt", session_id=sid)
        # SESSION_ID must come BEFORE PROMPT in `codex exec resume`.
        assert args.index(sid) < args.index("hello-prompt"), (
            "SESSION_ID must precede PROMPT in codex exec resume"
        )

    def test_prompt_is_always_last(self) -> None:
        runner = CodexRunner(command="codex", model="gpt-5.4")
        # New session
        args = runner._build_args("the-prompt", session_id=None)
        assert args[-1] == "the-prompt"
        # Resume
        args = runner._build_args("the-prompt", session_id="019e29a0-d5b0-71f0-bdc0-46f09a06fdaf")
        assert args[-1] == "the-prompt"

    def test_dangerously_bypass_flag_for_resume(self) -> None:
        sid = "019e29a0-d5b0-71f0-bdc0-46f09a06fdaf"
        runner = CodexRunner(
            command="codex",
            model="gpt-5.4",
            dangerously_skip_permissions=True,
        )
        args = runner._build_args("hi", session_id=sid)
        assert "--dangerously-bypass-approvals-and-sandbox" in args
        # Must precede SESSION_ID like the other flags
        assert args.index("--dangerously-bypass-approvals-and-sandbox") < args.index(sid)

    def test_no_lingering_resume_top_level_form(self) -> None:
        """`codex resume` (without `exec`) is NOT a valid codex CLI form."""
        sid = "019e29a0-d5b0-71f0-bdc0-46f09a06fdaf"
        runner = CodexRunner(command="codex", model="gpt-5.4")
        args = runner._build_args("hi", session_id=sid)
        # If 'resume' appears at index 1, that means we built `codex resume <id>`
        # which is rejected by codex. Must be at index 2 (after `exec`).
        if "resume" in args:
            assert args.index("resume") == 2, (
                f"resume must follow exec at index 2, got index {args.index('resume')}"
            )
