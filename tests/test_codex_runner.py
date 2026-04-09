"""Tests for CodexRunner argument building and minimal event translation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_discord.claude.types import MessageType
from claude_discord.codex.runner import CodexRunner


class TestBuildArgs:
    """Tests for CodexRunner._build_args()."""

    def test_new_session_uses_stdin_prompt_and_output_file(self, tmp_path: Path) -> None:
        runner = CodexRunner(command="codex", model="gpt-5-codex")

        output_path = tmp_path / "last.txt"
        args = runner._build_args(output_path=output_path, session_id=None)

        assert args[:2] == ["codex", "exec"]
        assert "--json" in args
        assert "--skip-git-repo-check" in args
        assert "--output-last-message" in args
        assert str(output_path) in args
        assert "--model" in args
        assert "gpt-5-codex" in args
        assert "--" in args
        assert args[-1] == "-"

    def test_resume_session_uses_resume_subcommand(self, tmp_path: Path) -> None:
        runner = CodexRunner(command="codex")

        output_path = tmp_path / "last.txt"
        args = runner._build_args(output_path=output_path, session_id="rollout-123")

        assert args[:3] == ["codex", "exec", "resume"]
        dashdash = args.index("--")
        assert args[dashdash + 1] == "rollout-123"
        assert args[dashdash + 2] == "-"

    def test_dangerously_skip_permissions_uses_bypass_flag(self, tmp_path: Path) -> None:
        runner = CodexRunner(dangerously_skip_permissions=True)

        args = runner._build_args(output_path=tmp_path / "last.txt", session_id=None)

        assert "--dangerously-bypass-approvals-and-sandbox" in args
        assert "--full-auto" not in args

    def test_working_dir_uses_cd_flag(self, tmp_path: Path) -> None:
        runner = CodexRunner(working_dir="/tmp/worktree")

        args = runner._build_args(output_path=tmp_path / "last.txt", session_id=None)

        assert "--cd" in args
        assert "/tmp/worktree" in args


class TestRun:
    """Tests for CodexRunner.run()."""

    @pytest.mark.asyncio
    async def test_run_yields_system_and_error_events(self, tmp_path: Path) -> None:
        runner = CodexRunner()

        stdout_lines = [
            b'{"type":"thread.started","thread_id":"rollout-123"}\n',
            b'{"type":"turn.started"}\n',
            b'{"type":"error","message":"Reconnecting... 1/5"}\n',
            (
                b'{"type":"turn.failed","error":{"message":"stream disconnected before completion"}}\n'
            ),
            b"",
        ]

        async def readline() -> bytes:
            return stdout_lines.pop(0)

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.close = MagicMock()

        mock_process = AsyncMock()
        mock_process.pid = 42
        mock_process.returncode = 1
        mock_process.stdin = mock_stdin
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(side_effect=readline)
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            events = [event async for event in runner.run("hello")]

        assert [event.message_type for event in events] == [MessageType.SYSTEM, MessageType.RESULT]
        assert events[0].session_id == "rollout-123"
        assert events[1].is_complete is True
        assert events[1].error == "stream disconnected before completion"

    @pytest.mark.asyncio
    async def test_run_uses_output_last_message_for_success(self, tmp_path: Path) -> None:
        runner = CodexRunner()

        stdout_lines = [
            b'{"type":"thread.started","thread_id":"rollout-456"}\n',
            b'{"type":"turn.started"}\n',
            b"",
        ]

        async def readline() -> bytes:
            return stdout_lines.pop(0)

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.close = MagicMock()

        mock_process = AsyncMock()
        mock_process.pid = 99
        mock_process.returncode = 0
        mock_process.stdin = mock_stdin
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(side_effect=readline)
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=0)

        created_output_path: Path | None = None
        real_build_args = runner._build_args

        def _capture_build_args(
            *,
            output_path: Path,
            session_id: str | None,
            image_paths: list[str] | None = None,
        ) -> list[str]:
            nonlocal created_output_path
            created_output_path = output_path
            return real_build_args(
                output_path=output_path,
                session_id=session_id,
                image_paths=image_paths,
            )

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch.object(runner, "_build_args", side_effect=_capture_build_args),
            patch.object(runner, "_read_last_message", return_value="final codex answer"),
        ):
            events = [event async for event in runner.run("hello")]

        assert created_output_path is not None
        assert [event.message_type for event in events] == [MessageType.SYSTEM, MessageType.RESULT]
        assert events[1].is_complete is True
        assert events[1].text == "final codex answer"

    @pytest.mark.asyncio
    async def test_prompt_is_written_to_stdin(self, tmp_path: Path) -> None:
        runner = CodexRunner()

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.close = MagicMock()

        mock_process = AsyncMock()
        mock_process.pid = 7
        mock_process.returncode = 0
        mock_process.stdin = mock_stdin
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(return_value=b"")
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            _ = [event async for event in runner.run("say hi")]

        mock_stdin.write.assert_called_once_with(b"say hi")
        mock_stdin.close.assert_called_once()
