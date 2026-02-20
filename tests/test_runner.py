"""Tests for ClaudeRunner argument building and environment handling."""

from __future__ import annotations

import os
import signal as signal_module
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_discord.claude.runner import ClaudeRunner


class TestBuildArgs:
    """Tests for _build_args method."""

    def setup_method(self) -> None:
        self.runner = ClaudeRunner(command="claude", model="sonnet")

    def test_basic_args(self) -> None:
        args = self.runner._build_args("hello", session_id=None)
        assert args[0] == "claude"
        assert "-p" in args
        assert "--output-format" in args
        assert "stream-json" in args
        assert "--model" in args
        assert "sonnet" in args
        # prompt should be after -- separator
        assert args[-1] == "hello"
        assert args[-2] == "--"

    def test_session_id_valid_uuid(self) -> None:
        sid = "241e0726-bbc3-40e7-9db0-086823acde26"
        args = self.runner._build_args("hello", session_id=sid)
        assert "--resume" in args
        assert sid in args

    def test_session_id_rejects_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid session_id"):
            self.runner._build_args("hello", session_id="--malicious-flag")

    def test_session_id_rejects_spaces(self) -> None:
        with pytest.raises(ValueError, match="Invalid session_id"):
            self.runner._build_args("hello", session_id="abc def")

    def test_prompt_after_double_dash(self) -> None:
        """Prompt starting with -- should not be interpreted as a flag."""
        args = self.runner._build_args("--help", session_id=None)
        idx = args.index("--")
        assert args[idx + 1] == "--help"

    def test_allowed_tools(self) -> None:
        runner = ClaudeRunner(allowed_tools=["Bash", "Read"])
        args = runner._build_args("hello", session_id=None)
        assert "--allowedTools" in args
        assert "Bash,Read" in args

    def test_dangerously_skip_permissions(self) -> None:
        runner = ClaudeRunner(dangerously_skip_permissions=True)
        args = runner._build_args("hello", session_id=None)
        assert "--dangerously-skip-permissions" in args

    def test_no_dangerously_skip_by_default(self) -> None:
        runner = ClaudeRunner()
        args = runner._build_args("hello", session_id=None)
        assert "--dangerously-skip-permissions" not in args

    def test_include_partial_messages_default(self) -> None:
        runner = ClaudeRunner()
        args = runner._build_args("hello", session_id=None)
        assert "--include-partial-messages" in args

    def test_include_partial_messages_disabled(self) -> None:
        runner = ClaudeRunner(include_partial_messages=False)
        args = runner._build_args("hello", session_id=None)
        assert "--include-partial-messages" not in args


class TestBuildEnv:
    """Tests for _build_env method."""

    def test_strips_claudecode(self) -> None:
        os.environ["CLAUDECODE"] = "1"
        try:
            runner = ClaudeRunner()
            env = runner._build_env()
            assert "CLAUDECODE" not in env
        finally:
            del os.environ["CLAUDECODE"]

    def test_strips_discord_token(self) -> None:
        os.environ["DISCORD_BOT_TOKEN"] = "secret-token"
        try:
            runner = ClaudeRunner()
            env = runner._build_env()
            assert "DISCORD_BOT_TOKEN" not in env
        finally:
            del os.environ["DISCORD_BOT_TOKEN"]

    def test_strips_discord_token_alt(self) -> None:
        os.environ["DISCORD_TOKEN"] = "secret-token"
        try:
            runner = ClaudeRunner()
            env = runner._build_env()
            assert "DISCORD_TOKEN" not in env
        finally:
            del os.environ["DISCORD_TOKEN"]

    def test_preserves_path(self) -> None:
        runner = ClaudeRunner()
        env = runner._build_env()
        assert "PATH" in env

    def test_injects_ccdb_api_url_when_api_port_set(self) -> None:
        runner = ClaudeRunner(api_port=8099)
        env = runner._build_env()
        assert env["CCDB_API_URL"] == "http://127.0.0.1:8099"

    def test_no_ccdb_api_url_when_api_port_not_set(self) -> None:
        runner = ClaudeRunner()
        env = runner._build_env()
        assert "CCDB_API_URL" not in env

    def test_injects_ccdb_api_secret_when_set(self) -> None:
        runner = ClaudeRunner(api_port=8099, api_secret="my-secret")
        env = runner._build_env()
        assert env["CCDB_API_SECRET"] == "my-secret"

    def test_no_ccdb_api_secret_when_not_set(self) -> None:
        runner = ClaudeRunner(api_port=8099)
        env = runner._build_env()
        assert "CCDB_API_SECRET" not in env


class TestClone:
    """Tests for clone method."""

    def test_clone_preserves_config(self) -> None:
        runner = ClaudeRunner(
            command="/usr/bin/claude",
            model="opus",
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            timeout_seconds=120,
            allowed_tools=["Bash", "Read"],
            dangerously_skip_permissions=True,
            include_partial_messages=False,
        )
        cloned = runner.clone()
        assert cloned.command == runner.command
        assert cloned.model == runner.model
        assert cloned.permission_mode == runner.permission_mode
        assert cloned.working_dir == runner.working_dir
        assert cloned.timeout_seconds == runner.timeout_seconds
        assert cloned.allowed_tools == runner.allowed_tools
        assert cloned.dangerously_skip_permissions == runner.dangerously_skip_permissions
        assert cloned.include_partial_messages == runner.include_partial_messages
        assert cloned._process is None


class TestInterrupt:
    """Tests for interrupt() method."""

    @pytest.mark.asyncio
    async def test_interrupt_no_process_is_noop(self) -> None:
        """interrupt() on a runner with no process should not raise."""
        runner = ClaudeRunner()
        await runner.interrupt()  # should not raise

    @pytest.mark.asyncio
    async def test_interrupt_already_exited_is_noop(self) -> None:
        """interrupt() when process already exited should not send a signal."""
        runner = ClaudeRunner()
        mock_process = MagicMock()
        mock_process.returncode = 0
        runner._process = mock_process
        await runner.interrupt()
        mock_process.send_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_interrupt_sends_sigint(self) -> None:
        """interrupt() sends SIGINT to the running process."""
        runner = ClaudeRunner()
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = AsyncMock(return_value=0)
        runner._process = mock_process

        await runner.interrupt()

        mock_process.send_signal.assert_called_once_with(signal_module.SIGINT)

    @pytest.mark.asyncio
    async def test_interrupt_falls_back_to_kill_on_timeout(self) -> None:
        """interrupt() calls kill() if the process doesn't stop within the timeout."""
        runner = ClaudeRunner()
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = AsyncMock(return_value=0)
        runner._process = mock_process

        with (
            patch("asyncio.wait_for", side_effect=TimeoutError),
            patch.object(runner, "kill", new_callable=AsyncMock) as mock_kill,
        ):
            await runner.interrupt()

        mock_process.send_signal.assert_called_once_with(signal_module.SIGINT)
        mock_kill.assert_called_once()


class TestSignalKillSuppression:
    """Tests that signal-killed processes (negative returncode) don't emit error events."""

    @pytest.mark.asyncio
    async def test_signal_kill_does_not_yield_error_event(self) -> None:
        """A process killed by signal (returncode < 0) exits silently — no error embed."""
        runner = ClaudeRunner()
        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stderr = AsyncMock()
        mock_process.returncode = -2  # SIGINT kill
        mock_process.stdout.readline = AsyncMock(return_value=b"")
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=-2)
        runner._process = mock_process

        events = [event async for event in runner._read_stream()]
        error_events = [e for e in events if e.error]
        assert error_events == [], "Signal kill should not produce error events"

    @pytest.mark.asyncio
    async def test_positive_nonzero_returncode_yields_error(self) -> None:
        """A process that exits with a positive non-zero code yields an error event."""
        runner = ClaudeRunner()
        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stderr = AsyncMock()
        mock_process.returncode = 1
        mock_process.stdout.readline = AsyncMock(return_value=b"")
        mock_process.stderr.read = AsyncMock(return_value=b"error details")
        mock_process.wait = AsyncMock(return_value=1)
        runner._process = mock_process

        events = [event async for event in runner._read_stream()]
        error_events = [e for e in events if e.error]
        assert len(error_events) == 1
        assert "1" in error_events[0].error
