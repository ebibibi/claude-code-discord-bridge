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
import re
import signal
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
        allowed_tools: list[str] | None = None,
        dangerously_skip_permissions: bool = False,
        include_partial_messages: bool = True,
        api_port: int | None = None,
        api_secret: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        self.command = command
        self.model = model
        self.permission_mode = permission_mode
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self.allowed_tools = allowed_tools
        self.dangerously_skip_permissions = dangerously_skip_permissions
        self.include_partial_messages = include_partial_messages
        self.api_port = api_port
        self.api_secret = api_secret
        self.thread_id = thread_id
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
        except TimeoutError:
            logger.warning("Claude CLI timed out after %ds", self.timeout_seconds)
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                error=f"Timed out after {self.timeout_seconds} seconds",
            )
        finally:
            await self._cleanup()

    def clone(self, thread_id: int | None = None) -> ClaudeRunner:
        """Create a fresh runner with the same configuration but no active process.

        Args:
            thread_id: Discord thread ID to inject as DISCORD_THREAD_ID env var.
                       Overrides the instance-level thread_id if provided.
        """
        return ClaudeRunner(
            command=self.command,
            model=self.model,
            permission_mode=self.permission_mode,
            working_dir=self.working_dir,
            timeout_seconds=self.timeout_seconds,
            allowed_tools=self.allowed_tools,
            dangerously_skip_permissions=self.dangerously_skip_permissions,
            include_partial_messages=self.include_partial_messages,
            api_port=self.api_port,
            api_secret=self.api_secret,
            thread_id=thread_id if thread_id is not None else self.thread_id,
        )

    async def interrupt(self) -> None:
        """Interrupt the subprocess with SIGINT (graceful stop, like Ctrl+C / Escape).

        Gives Claude Code a chance to flush output and preserve session state
        before exiting.  Falls back to kill() if the process does not stop
        within 10 seconds.
        """
        if self._process and self._process.returncode is None:
            self._process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except TimeoutError:
                await self.kill()

    async def kill(self) -> None:
        """Terminate the subprocess, force-killing if it doesn't stop in time."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()

    def _build_args(self, prompt: str, session_id: str | None) -> list[str]:
        """Build command-line arguments for claude CLI.

        All arguments are passed as a list to create_subprocess_exec,
        which does NOT invoke a shell, preventing injection.
        """
        args = [
            self.command,
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
            "--verbose",
        ]

        if self.include_partial_messages:
            args.append("--include-partial-messages")

        if self.dangerously_skip_permissions:
            args.append("--dangerously-skip-permissions")

        if self.allowed_tools:
            args.extend(["--allowedTools", ",".join(self.allowed_tools)])

        if session_id:
            if not re.match(r"^[a-f0-9\-]+$", session_id):
                raise ValueError(f"Invalid session_id format: {session_id!r}")
            args.extend(["--resume", session_id])

        # Use -- to separate flags from positional args (prevents prompt
        # content starting with - from being interpreted as a flag)
        args.append("--")
        args.append(prompt)
        return args

    # Environment variables that must never leak to the CLI subprocess.
    _STRIPPED_ENV_KEYS = frozenset(
        {
            "CLAUDECODE",
            "DISCORD_BOT_TOKEN",
            "DISCORD_TOKEN",
            "API_SECRET_KEY",
        }
    )

    def _build_env(self) -> dict[str, str]:
        """Build environment variables for the subprocess.

        Strips CLAUDECODE (nesting detection) and known secret variables
        so that the CLI process cannot read them via Bash tool.

        Injects CCDB_API_URL (and optionally CCDB_API_SECRET) so Claude Code
        can register scheduled tasks via ``curl $CCDB_API_URL/api/tasks``.
        """
        env = {k: v for k, v in os.environ.items() if k not in self._STRIPPED_ENV_KEYS}
        if self.api_port is not None:
            env["CCDB_API_URL"] = f"http://127.0.0.1:{self.api_port}"
        if self.api_secret is not None:
            env["CCDB_API_SECRET"] = self.api_secret
        if self.thread_id is not None:
            env["DISCORD_THREAD_ID"] = str(self.thread_id)
        return env

    async def _read_stream(self) -> AsyncGenerator[StreamEvent, None]:
        """Read and parse stdout line by line."""
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Process not started")

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

        if self._process.returncode is not None and self._process.returncode > 0:
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
                error=f"CLI exited with code {self._process.returncode}",
            )

    async def _cleanup(self) -> None:
        """Ensure the subprocess is properly terminated after run() exits."""
        await self.kill()
