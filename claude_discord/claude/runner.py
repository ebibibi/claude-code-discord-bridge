"""Claude Code CLI runner.

Spawns `claude -p --output-format stream-json` as an async subprocess
and yields StreamEvent objects.

Security note: We use create_subprocess_exec (not shell=True) to safely
pass user prompts as arguments without shell injection risk.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator

from .parser import parse_line
from .types import MessageType, StreamEvent

logger = logging.getLogger(__name__)


class ClaudeRunner:
    """Manages Claude Code CLI subprocess execution."""

    def __init__(
        self,
        command: str = "claude",
        model: str = "sonnet",
        permission_mode: str = "acceptEdits",
        working_dir: str | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.command = command
        self.model = model
        self.permission_mode = permission_mode
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self._process: asyncio.subprocess.Process | None = None

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run Claude Code CLI and yield stream events.

        Uses create_subprocess_exec (not shell) to avoid injection risks.
        The prompt is passed as a direct argument to the claude binary.

        Args:
            prompt: The user's message/prompt.
            session_id: Optional session ID to resume.

        Yields:
            StreamEvent objects parsed from stream-json output.
        """
        args = self._build_args(prompt, session_id)
        env = self._build_env()
        cwd = self.working_dir or os.getcwd()

        logger.info("Starting Claude CLI: %s", " ".join(args[:6]) + " ...")

        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            limit=10 * 1024 * 1024,  # 10MB — stream-json lines can be large
        )

        try:
            async for event in self._read_stream():
                yield event
        except asyncio.TimeoutError:
            logger.warning("Claude CLI timed out after %ds", self.timeout_seconds)
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                error=f"Timed out after {self.timeout_seconds} seconds",
            )
        finally:
            await self._cleanup()

    async def kill(self) -> None:
        """Kill the running subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()

    def _build_args(self, prompt: str, session_id: str | None) -> list[str]:
        """Build command-line arguments for claude CLI.

        All arguments are passed as a list to create_subprocess_exec,
        which does NOT invoke a shell, preventing injection.
        """
        args = [
            self.command,
            "-p",
            "--output-format", "stream-json",
            "--model", self.model,
            "--permission-mode", self.permission_mode,
            "--verbose",
        ]

        if session_id:
            args.extend(["--resume", session_id])

        args.append(prompt)
        return args

    def _build_env(self) -> dict[str, str]:
        """Build environment variables, ensuring CLAUDECODE is unset."""
        env = os.environ.copy()
        # Must unset CLAUDECODE to avoid nesting detection
        env.pop("CLAUDECODE", None)
        return env

    async def _read_stream(self) -> AsyncGenerator[StreamEvent, None]:
        """Read and parse stdout line by line."""
        assert self._process is not None
        assert self._process.stdout is not None

        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            event = parse_line(decoded)
            if event:
                yield event
                if event.is_complete:
                    return

        # If we reach here without a result event, check for errors
        if self._process.returncode is None:
            await asyncio.wait_for(self._process.wait(), timeout=10)

        if self._process.returncode and self._process.returncode != 0:
            stderr_data = b""
            if self._process.stderr:
                stderr_data = await self._process.stderr.read()
            stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
            logger.error(
                "Claude CLI exited with code %d: %s",
                self._process.returncode,
                stderr_text[:200],
            )
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                error=f"CLI exited with code {self._process.returncode}: {stderr_text[:500]}",
            )

    async def _cleanup(self) -> None:
        """Ensure the subprocess is properly terminated."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
