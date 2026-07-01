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
from urllib.parse import urlparse

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

# Reasoning-effort levels accepted by the Codex CLI / GPT-5.x models. Used to
# validate the value before it is injected into a `-c model_reasoning_effort=`
# config override (defence-in-depth against config injection).
VALID_CODEX_EFFORTS: frozenset[str] = frozenset({"minimal", "low", "medium", "high", "xhigh"})


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
            # USER (not ASSISTANT): EventProcessor only cancels the live elapsed
            # timer and finalizes the tool embed on USER events (_on_tool_result).
            # Tagging this ASSISTANT leaves the timer running forever.
            return StreamEvent(
                raw=data,
                message_type=MessageType.USER,
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


# Codex item types that arrive as a single ``item.completed`` with no preceding
# ``item.started`` (atomic tools). The EventProcessor opens a tool embed and a
# live elapsed timer for every tool_use, and only stops it when a matching tool
# result arrives. For atomic tools no result would ever come, so the timer would
# accumulate forever — we synthesize a completion to close it immediately.
_ATOMIC_ITEM_TYPES: frozenset[str] = frozenset({"file_changes"})
_MISSING_ROLLOUT_PATTERN = re.compile(r"no rollout found for thread id", re.IGNORECASE)


def _atomic_tool_completion(event: StreamEvent) -> StreamEvent | None:
    """Return a synthetic tool-result event for an atomic Codex tool_use.

    Returns None for events that are not atomic tool_use events (e.g. a
    ``command_execution`` start, which has its own completion event).
    """
    if event.tool_use is None:
        return None
    item_type = event.raw.get("item", {}).get("type", "")
    if item_type not in _ATOMIC_ITEM_TYPES:
        return None
    return StreamEvent(
        raw=event.raw,
        message_type=MessageType.USER,
        tool_result_id=event.tool_use.tool_id,
        tool_result_content="",
    )


def _is_missing_rollout_error(error: str | None) -> bool:
    """Return True when Codex cannot resume because local rollout history is gone."""
    return bool(error and _MISSING_ROLLOUT_PATTERN.search(error))


class CodexRunner:
    """Manages OpenAI Codex CLI subprocess."""

    def __init__(
        self,
        command: str = "codex",
        model: str | None = None,
        permission_mode: str = "default",
        working_dir: str | None = None,
        timeout_seconds: int = 300,
        dangerously_skip_permissions: bool = False,
        allowed_tools: list[str] | None = None,
        api_port: int | None = None,
        api_secret: str | None = None,
        thread_id: int | None = None,
        images: list[ImageData] | None = None,
        effort: str | None = None,
        **_kwargs: object,
    ) -> None:
        self.command = command
        # ``model`` is optional: when falsy we omit ``--model`` so the Codex
        # CLI falls back to its own default (``model`` in ~/.codex/config.toml,
        # currently gpt-5.5). This keeps ccdb in lock-step with the console
        # default instead of pinning a version that goes stale.
        self.model = model
        # ``effort`` maps to Codex's ``model_reasoning_effort`` config value.
        # None means "defer to the CLI default" (config.toml, currently high).
        self.effort = effort
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
        attempt_session_id = session_id
        retried_without_resume = False

        while True:
            args = self._build_args(prompt, attempt_session_id)
            env = self._build_env()
            cwd = self.working_dir or os.getcwd()
            should_retry_without_resume = False

            logger.info("Starting Codex CLI: %s (cwd=%s)", " ".join(args[:6]) + " ...", cwd)

            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                limit=10 * 1024 * 1024,
            )

            logger.info("Codex CLI started: pid=%s", self._process.pid)

            if self._process.stdin is not None:
                await self._send_prompt(prompt)

            try:
                async for event in self._read_stream():
                    if (
                        attempt_session_id
                        and not retried_without_resume
                        and _is_missing_rollout_error(event.error)
                    ):
                        logger.warning(
                            "Codex resume history for session %s is missing; "
                            "starting a new session instead",
                            attempt_session_id,
                        )
                        should_retry_without_resume = True
                        retried_without_resume = True
                        break
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

            if should_retry_without_resume:
                attempt_session_id = None
                continue
            return

    def clone(
        self,
        model: str | None = None,
        working_dir: str | None | object = _UNSET,
        thread_id: int | None = None,
        effort: str | None | object = _UNSET,
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
            effort=self.effort if effort is _UNSET else effort,  # type: ignore[arg-type]
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

    async def _send_prompt(self, prompt: str) -> None:
        """Write the initial prompt to stdin and close it.

        ``codex exec -`` and ``codex exec resume <session_id> -`` read the
        prompt from stdin. Keeping the prompt out of argv avoids OS E2BIG /
        ``Argument list too long`` failures for large Discord attachments.
        """
        assert self._process is not None and self._process.stdin is not None
        try:
            self._process.stdin.write(prompt.encode())
            await self._process.stdin.drain()
            self._process.stdin.close()
            wait_closed = getattr(self._process.stdin, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("Codex stdin closed before prompt write completed", exc_info=True)
        except Exception:
            logger.warning("_send_prompt: failed to write to stdin", exc_info=True)

    def _build_args(self, prompt: str, session_id: str | None) -> list[str]:
        """Build command-line arguments for codex CLI.

        Codex CLI structure (verified against v0.124):
            codex exec [OPTIONS] [PROMPT]
            codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]

        Both subcommands accept --json and --model. We pass "-" as the prompt
        positional so Codex reads the actual prompt from stdin instead of argv.
        The resume positional args come AFTER any flags, with SESSION_ID before
        the stdin marker.
        """
        # Always under the `exec` subcommand. `resume` is its sub-subcommand.
        args = [self.command, "exec"]
        if session_id:
            if not re.match(r"^[a-f0-9\-]+$", session_id):
                raise ValueError(f"Invalid session_id format: {session_id!r}")
            args.append("resume")

        args.append("--json")
        if self.model:
            args.extend(["--model", self.model])
        if self.effort:
            if self.effort not in VALID_CODEX_EFFORTS:
                raise ValueError(
                    f"Invalid Codex effort {self.effort!r}; "
                    f"choose one of {', '.join(sorted(VALID_CODEX_EFFORTS))}"
                )
            args.extend(["-c", f"model_reasoning_effort={self.effort}"])

        if self.dangerously_skip_permissions:
            args.append("--dangerously-bypass-approvals-and-sandbox")
        elif self.permission_mode in _APPROVAL_MODE_MAP:
            args.extend(["--ask-for-approval", _APPROVAL_MODE_MAP[self.permission_mode]])

        # --cd is only accepted by `codex exec`, not by `codex exec resume`.
        if self.working_dir and not session_id:
            args.extend(["--cd", self.working_dir])

        # Positional args come last. For resume: SESSION_ID then stdin marker.
        if session_id:
            args.append(session_id)
        args.append("-")
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

    def describe_api(self) -> str:
        """Return a short label for the API endpoint this runner targets."""
        env = self._build_env()
        base_url = (env.get("OPENAI_BASE_URL") or "").strip()
        if base_url:
            host = urlparse(base_url).hostname or base_url
            return f"Custom endpoint ({host})"
        return "OpenAI API (direct)"

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
                # Atomic tools (e.g. file_changes) have no completion event of
                # their own; pair them with a synthetic result so the live
                # elapsed timer is cancelled instead of accumulating forever.
                completion = _atomic_tool_completion(event)
                if completion is not None:
                    yield completion

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
            error = f"CLI exited with code {self._process.returncode}"
            if stderr_text:
                error = f"{error}: {stderr_text[:1000]}"
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                error=error,
            )

    async def _cleanup(self) -> None:
        """Ensure the subprocess is properly terminated."""
        await self.kill()
