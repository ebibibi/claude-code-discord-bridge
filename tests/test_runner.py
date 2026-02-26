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

    def test_append_system_prompt_included(self) -> None:
        """--append-system-prompt flag is added when set."""
        runner = ClaudeRunner(append_system_prompt="You are in a concurrent env.")
        args = runner._build_args("hello", session_id=None)
        assert "--append-system-prompt" in args
        idx = args.index("--append-system-prompt")
        assert args[idx + 1] == "You are in a concurrent env."

    def test_append_system_prompt_before_double_dash(self) -> None:
        """--append-system-prompt must appear before the -- separator."""
        runner = ClaudeRunner(append_system_prompt="ctx")
        args = runner._build_args("hello", session_id=None)
        sp_idx = args.index("--append-system-prompt")
        dd_idx = args.index("--")
        assert sp_idx < dd_idx

    def test_no_append_system_prompt_by_default(self) -> None:
        runner = ClaudeRunner()
        args = runner._build_args("hello", session_id=None)
        assert "--append-system-prompt" not in args

    def test_clone_propagates_append_system_prompt(self) -> None:
        """clone() with append_system_prompt overrides the parent value."""
        base = ClaudeRunner(append_system_prompt="old context")
        cloned = base.clone(append_system_prompt="new context")
        assert cloned.append_system_prompt == "new context"

    def test_clone_inherits_append_system_prompt(self) -> None:
        """clone() without append_system_prompt inherits parent value."""
        base = ClaudeRunner(append_system_prompt="persistent context")
        cloned = base.clone()
        assert cloned.append_system_prompt == "persistent context"

    def test_clone_none_inherits_parent_append_system_prompt(self) -> None:
        """clone(append_system_prompt=None) inherits parent value (None means 'not provided')."""
        base = ClaudeRunner(append_system_prompt="ctx")
        cloned = base.clone(append_system_prompt=None)
        assert cloned.append_system_prompt == "ctx"  # inherits parent


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
        # Remove CCDB_API_URL from the process env so it isn't inherited
        original = os.environ.pop("CCDB_API_URL", None)
        try:
            runner = ClaudeRunner()
            env = runner._build_env()
            assert "CCDB_API_URL" not in env
        finally:
            if original is not None:
                os.environ["CCDB_API_URL"] = original

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

    @pytest.mark.asyncio
    async def test_interrupt_falls_back_to_kill_on_asyncio_timeout(self) -> None:
        """interrupt() calls kill() on asyncio.TimeoutError (Python 3.10 compat).

        On Python 3.10, asyncio.TimeoutError is NOT a subclass of the built-in
        TimeoutError.  This test verifies the correct exception is caught so
        interrupt() doesn't propagate an unhandled exception to the caller.
        """
        import asyncio

        runner = ClaudeRunner()
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = AsyncMock(return_value=0)
        runner._process = mock_process

        with (
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
            patch.object(runner, "kill", new_callable=AsyncMock) as mock_kill,
        ):
            await runner.interrupt()  # must not raise

        mock_process.send_signal.assert_called_once_with(signal_module.SIGINT)
        mock_kill.assert_called_once()


class TestKill:
    """Tests for kill() method."""

    @pytest.mark.asyncio
    async def test_kill_force_kills_on_asyncio_timeout(self) -> None:
        """kill() force-kills the process on asyncio.TimeoutError (Python 3.10 compat).

        On Python 3.10, asyncio.TimeoutError is NOT a subclass of the built-in
        TimeoutError.  Verify kill() still calls process.kill() rather than
        propagating an unhandled exception.
        """
        import asyncio

        runner = ClaudeRunner()
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = AsyncMock(return_value=0)
        runner._process = mock_process

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await runner.kill()  # must not raise

        mock_process.kill.assert_called_once()


class TestRunTimeout:
    """Tests for timeout handling in run()."""

    @pytest.mark.asyncio
    async def test_run_yields_error_on_asyncio_timeout(self) -> None:
        """run() yields a timeout error event on asyncio.TimeoutError (Python 3.10 compat).

        On Python 3.10, asyncio.TimeoutError is NOT a subclass of the built-in
        TimeoutError.  Verify run() catches it and yields a proper error event
        instead of propagating the exception to callers.
        """

        runner = ClaudeRunner(timeout_seconds=5)

        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.stdout = AsyncMock()
        mock_process.stderr = AsyncMock()

        async def _stream_raises():
            raise TimeoutError
            yield  # make it an async generator

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch.object(runner, "_read_stream", _stream_raises),
            patch.object(runner, "_cleanup", new_callable=AsyncMock),
        ):
            events = [event async for event in runner.run("hello")]

        assert len(events) == 1
        assert events[0].is_complete
        assert events[0].error is not None
        assert "imed out" in events[0].error


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

    def test_clone_with_model_override(self) -> None:
        """clone() with model= overrides the runner's model for that clone."""
        runner = ClaudeRunner(model="sonnet")
        cloned = runner.clone(model="opus")
        assert cloned.model == "opus"
        assert runner.model == "sonnet"  # original unchanged

    def test_clone_without_model_override_preserves_model(self) -> None:
        """clone() without model= keeps the original model."""
        runner = ClaudeRunner(model="haiku")
        cloned = runner.clone()
        assert cloned.model == "haiku"


class TestImageStreamJson:
    """Tests for --input-format stream-json image attachment support.

    Regression tests for the bug where --image flags were added to the CLI
    args even though the flag does not exist in claude CLI.  Images must be
    passed via --input-format stream-json / stdin instead.

    See: https://github.com/ebibibi/claude-code-discord-bridge/issues/177
    """

    def test_no_image_flag_in_args(self) -> None:
        """_build_args() must NOT produce --image flags (flag does not exist)."""
        runner = ClaudeRunner(image_paths=["/tmp/photo.png"])
        args = runner._build_args("look at this", session_id=None)
        assert "--image" not in args

    def test_stream_json_input_format_added_for_images(self) -> None:
        """_build_args() adds --input-format stream-json when image_paths is set."""
        runner = ClaudeRunner(image_paths=["/tmp/photo.png"])
        args = runner._build_args("look at this", session_id=None)
        assert "--input-format" in args
        idx = args.index("--input-format")
        assert args[idx + 1] == "stream-json"

    def test_prompt_not_in_cli_args_when_images_present(self) -> None:
        """Prompt must NOT appear as a CLI arg when using stream-json input.

        In stream-json mode the prompt is part of the JSON sent to stdin.
        Passing it as a CLI arg as well would cause a duplicate-input error.
        """
        runner = ClaudeRunner(image_paths=["/tmp/photo.png"])
        args = runner._build_args("look at this", session_id=None)
        # Double-dash separator must not be present
        assert "--" not in args
        # Prompt must not appear as a positional arg
        assert "look at this" not in args

    def test_no_stream_json_input_format_without_images(self) -> None:
        """Without image_paths, --input-format stream-json is NOT added."""
        runner = ClaudeRunner()
        args = runner._build_args("hello", session_id=None)
        assert "--input-format" not in args

    def test_prompt_in_cli_args_without_images(self) -> None:
        """Without images, prompt is still passed as a CLI arg (existing behaviour)."""
        runner = ClaudeRunner()
        args = runner._build_args("hello", session_id=None)
        assert args[-1] == "hello"
        assert args[-2] == "--"

    @pytest.mark.asyncio
    async def test_send_stream_json_message_writes_to_stdin(self) -> None:
        """_send_stream_json_message() writes a JSON user message to stdin."""
        import base64
        import json
        import tempfile

        # Write a tiny valid PNG to a tempfile
        png_1x1 = base64.standard_b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQ"
            "AABjkB6QAAAABJRU5ErkJggg=="
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_1x1)
            img_path = f.name

        try:
            runner = ClaudeRunner(image_paths=[img_path])

            stdin_mock = AsyncMock()
            stdin_mock.drain = AsyncMock()

            mock_process = MagicMock()
            mock_process.stdin = stdin_mock
            runner._process = mock_process

            await runner._send_stream_json_message("describe this image")

            # stdin.write must have been called with a JSON line
            stdin_mock.write.assert_called_once()
            raw_bytes = stdin_mock.write.call_args[0][0]
            payload = json.loads(raw_bytes.decode())

            assert payload["type"] == "user"
            content = payload["message"]["content"]
            # First block: image
            assert content[0]["type"] == "image"
            assert content[0]["source"]["type"] == "base64"
            assert content[0]["source"]["media_type"] == "image/png"
            # Second block: text prompt
            assert content[-1]["type"] == "text"
            assert content[-1]["text"] == "describe this image"
        finally:
            import os

            os.unlink(img_path)

    @pytest.mark.asyncio
    async def test_send_stream_json_message_uses_pipe_stdin(self) -> None:
        """run() uses stdin=PIPE (not DEVNULL) when image_paths is set."""
        import asyncio as _asyncio

        runner = ClaudeRunner(image_paths=["/nonexistent/test.png"])

        async def fake_events():
            yield  # empty generator

        mock_process = AsyncMock()
        mock_process.pid = 42
        mock_process.returncode = None
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(return_value=b"")
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.stdin = AsyncMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.wait = AsyncMock(return_value=0)

        with (
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ) as mock_exec,
            patch.object(runner, "_cleanup", new_callable=AsyncMock),
        ):
            # Consume the generator (image file doesn't exist — _send will log warning)
            _ = [event async for event in runner.run("test")]

        # Verify stdin was PIPE (not DEVNULL)
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["stdin"] == _asyncio.subprocess.PIPE
