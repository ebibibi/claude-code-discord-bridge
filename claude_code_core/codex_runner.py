"""OpenAI Codex CLI runner.

Spawns the codex CLI as an async subprocess and yields StreamEvent
objects, providing the same interface as ClaudeRunner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
from collections.abc import AsyncGenerator

from .types import (
    ImageData,
    MessageType,
    StreamEvent,
    ToolCategory,
    ToolUseEvent,
)

logger = logging.getLogger(__name__)

_UNSET = object()

_APPROVAL_MODE_MAP: dict[str, str] = {
    "acceptEdits": "except-edit",
    "full": "always",
    "none": "never",
}


def parse_codex_line(line: str) -> StreamEvent | None:
    """Parse a single Codex JSONL line into a StreamEvent."""
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = data.get("type", "")

    if event_type == "thread.started":
        return StreamEvent(
            raw=data,
            message_type=MessageType.SYSTEM,
            session_id=data.get("thread_id"),
        )

    if event_type == "turn.started":
        return StreamEvent(raw=data, message_type=MessageType.SYSTEM)

    if event_type == "turn.completed":
        usage = data.get("usage", {})
        return StreamEvent(
            raw=data,
            message_type=MessageType.SYSTEM,
            is_complete=True,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cached_input_tokens"),
        )

    if event_type == "error":
        return StreamEvent(
            raw=data,
            message_type=MessageType.RESULT,
            is_complete=True,
            error=data.get("message", "Unknown error"),
        )

    item = data.get("item", {})
    item_type = item.get("type", "")

    if event_type == "item.started" and item_type == "command_execution":
        return StreamEvent(
            raw=data,
            message_type=MessageType.ASSISTANT,
            tool_use=ToolUseEvent(
                tool_id=item.get("id", ""),
                tool_name="Bash",
                tool_input={"command": item.get("command", "")},
                category=ToolCategory.COMMAND,
            ),
        )

    if event_type == "item.completed":
        if item_type == "agent_message":
            return StreamEvent(
                raw=data,
                message_type=MessageType.ASSISTANT,
                text=item.get("text", ""),
            )

        if item_type == "command_execution":
            return StreamEvent(
                raw=data,
                message_type=MessageType.ASSISTANT,
                tool_result_id=item.get("id", ""),
                tool_result_content=item.get("output", ""),
            )

        if item_type == "file_changes":
            return StreamEvent(
                raw=data,
                message_type=MessageType.ASSISTANT,
                tool_use=ToolUseEvent(
                    tool_id=item.get("id", ""),
                    tool_name="Edit",
                    tool_input={"description": item.get("text", "")},
                    category=ToolCategory.EDIT,
                ),
            )

    return None


class CodexRunner:
    """Manages OpenAI Codex CLI subprocess."""

    def __init__(
        self,
        command: str = "codex",
        model: str = "o4-mini",
        permission_mode: str = "default",
        working_dir: str | None = None,
        timeout_seconds: int = 300,
        dangerously_skip_permissions: bool = False,
        allowed_tools: list[str] | None = None,
        api_port: int | None = None,
        api_secret: str | None = None,
        thread_id: int | None = None,
        images: list[ImageData] | None = None,
        **_kwargs: object,
    ) -> None:
        self.command = command
        self.model = model
        self.permission_mode = permission_mode
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self.dangerously_skip_permissions = dangerously_skip_permissions
        self.allowed_tools = allowed_tools
        self.api_port = api_port
        self.api_secret = api_secret
        self.thread_id = thread_id
        self.images = images
        self._process: asyncio.subprocess.Process | None = None

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run Codex CLI and yield stream events."""
        args = self._build_args(prompt, session_id)
        env = self._build_env()
        cwd = self.working_dir or os.getcwd()

        logger.info("Starting Codex CLI: %s (cwd=%s)", " ".join(args[:6]) + " ...", cwd)

        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            limit=10 * 1024 * 1024,
        )

        logger.info("Codex CLI started: pid=%s", self._process.pid)

        try:
            async for event in self._read_stream():
                yield event
        except TimeoutError:
            logger.warning("Codex CLI timed out after %ds", self.timeout_seconds)
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                error=f"Timed out after {self.timeout_seconds} seconds",
            )
        finally:
            await self._cleanup()

    def clone(
        self,
        model: str | None = None,
        working_dir: str | None | object = _UNSET,
        thread_id: int | None = None,
        **_kwargs: object,
    ) -> CodexRunner:
        """Create a fresh runner with the same configuration but no active process."""
        return CodexRunner(
            command=self.command,
            model=model if model is not None else self.model,
            permission_mode=self.permission_mode,
            working_dir=(
                self.working_dir if working_dir is _UNSET else working_dir  # type: ignore[arg-type]
            ),
            timeout_seconds=self.timeout_seconds,
            dangerously_skip_permissions=self.dangerously_skip_permissions,
            allowed_tools=self.allowed_tools,
            api_port=self.api_port,
            api_secret=self.api_secret,
            thread_id=thread_id if thread_id is not None else self.thread_id,
            images=self.images,
        )

    async def interrupt(self) -> None:
        """Interrupt the subprocess with SIGINT."""
        if self._process and self._process.returncode is None:
            if os.name == "nt":
                self._process.terminate()
            else:
                self._process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except TimeoutError:
                await self.kill()

    async def kill(self) -> None:
        """Terminate the subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()

    async def inject_tool_result(self, request_id: str, data: dict) -> None:
        """Codex CLI does not support stdin injection; this is a no-op."""
        logger.debug("inject_tool_result called on CodexRunner (no-op): %s", request_id)

    def _build_args(self, prompt: str, session_id: str | None) -> list[str]:
        """Build command-line arguments for codex CLI.

        Codex CLI structure (verified against v0.124):
            codex exec [OPTIONS] [PROMPT]
            codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]

        Both subcommands accept --json and --model. The resume positional
        args come AFTER any flags, with SESSION_ID before PROMPT.
        """
        # Always under the `exec` subcommand. `resume` is its sub-subcommand.
        args = [self.command, "exec"]
        if session_id:
            if not re.match(r"^[a-f0-9\-]+$", session_id):
                raise ValueError(f"Invalid session_id format: {session_id!r}")
            args.append("resume")

        args.extend(["--json", "--model", self.model])

        if self.dangerously_skip_permissions:
            args.append("--dangerously-bypass-approvals-and-sandbox")
        elif self.permission_mode in _APPROVAL_MODE_MAP:
            args.extend(["--ask-for-approval", _APPROVAL_MODE_MAP[self.permission_mode]])

        if self.working_dir:
            args.extend(["--cd", self.working_dir])

        # Positional args come last. For resume: SESSION_ID then PROMPT.
        if session_id:
            args.append(session_id)
        args.append(prompt)
        return args

    _STRIPPED_ENV_KEYS = frozenset(
        {
            "CLAUDECODE",
            "DISCORD_BOT_TOKEN",
            "DISCORD_TOKEN",
            "API_SECRET_KEY",
        }
    )

    def _build_env(self) -> dict[str, str]:
        """Build environment variables for the subprocess."""
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
            event = parse_codex_line(decoded)
            if event:
                yield event
                if event.is_complete:
                    return

        if self._process.returncode is None:
            await asyncio.wait_for(self._process.wait(), timeout=10)

        if self._process.returncode is not None and self._process.returncode > 0:
            stderr_data = b""
            if self._process.stderr:
                stderr_data = await self._process.stderr.read()
            stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
            logger.error(
                "Codex CLI exited with code %d: %s",
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
        """Ensure the subprocess is properly terminated."""
        await self.kill()
