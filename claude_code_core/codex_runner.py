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
from pathlib import Path
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
_RESUME_STREAM_DISCONNECT_PATTERN = re.compile(
    r"stream disconnected before completion:.*"
    r"websocket closed by server before response\.completed",
    re.IGNORECASE,
)
_RECOVERY_MESSAGE_LIMIT = 12
_RECOVERY_MESSAGE_CHARS = 4_000
_RECOVERY_TRANSCRIPT_CHARS = 24_000


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


def _is_resume_stream_disconnect(error: str | None) -> bool:
    """Return True for the persistent Codex Responses WebSocket failure."""
    return bool(error and _RESUME_STREAM_DISCONNECT_PATTERN.search(error))


def _find_rollout(session_id: str, env: dict[str, str]) -> Path | None:
    """Find Codex's local rollout for a validated session ID."""
    codex_home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.is_dir():
        return None
    return next(sessions_dir.rglob(f"*-{session_id}.jsonl"), None)


def _text_transcript_from_rollout(session_id: str, env: dict[str, str]) -> str:
    """Extract bounded user/assistant text without loading image/tool payloads.

    Failed resume attempts append user messages without a matching assistant
    response. Trim that incomplete tail because the current prompt is included
    separately in the recovery request.
    """
    rollout = _find_rollout(session_id, env)
    if rollout is None:
        return ""

    messages: list[tuple[str, str]] = []
    last_assistant_index: int | None = None
    try:
        with rollout.open(encoding="utf-8") as stream:
            for line in stream:
                # Image/tool records can be several megabytes. Reject them
                # before JSON parsing and retain only lightweight event_msg text.
                if '"event_msg"' not in line:
                    continue
                if '"user_message"' not in line and '"agent_message"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = record.get("payload", {})
                event_type = payload.get("type")
                message = payload.get("message")
                if event_type not in {"user_message", "agent_message"} or not isinstance(
                    message, str
                ):
                    continue
                role = "User" if event_type == "user_message" else "Assistant"
                messages.append((role, message[:_RECOVERY_MESSAGE_CHARS]))
                if role == "Assistant":
                    last_assistant_index = len(messages) - 1
    except OSError:
        logger.warning("Could not read Codex rollout for recovery", exc_info=True)
        return ""

    if last_assistant_index is not None:
        messages = messages[: last_assistant_index + 1]
    messages = messages[-_RECOVERY_MESSAGE_LIMIT:]
    transcript = "\n\n".join(f"{role}:\n{text}" for role, text in messages)
    return transcript[-_RECOVERY_TRANSCRIPT_CHARS:]


def _build_resume_recovery_prompt(prompt: str, session_id: str, env: dict[str, str]) -> str:
    """Build a text-only handoff when a Codex resume is permanently stuck."""
    transcript = _text_transcript_from_rollout(session_id, env)
    context = transcript or "(No prior text transcript was available.)"
    return (
        "A previous Codex session could not be resumed after exhausting its transport retries. "
        "Continue the same task in this replacement session. Use the text-only transcript below "
        "for intent, inspect the current workspace for the authoritative work state, and do not "
        "repeat completed work.\n\n"
        f"Previous text transcript:\n{context}\n\n"
        f"Current user message:\n{prompt}"
    )


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
        append_system_prompt: str | None = None,
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
        self.append_system_prompt = append_system_prompt
        self.images = images
        self._process: asyncio.subprocess.Process | None = None

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run Codex CLI and yield stream events."""
        attempt_session_id = session_id
        attempt_prompt = prompt
        retried_without_resume = False

        while True:
            args = self._build_args(attempt_prompt, attempt_session_id)
            env = self._build_env()
            cwd = self.working_dir or os.getcwd()
            should_retry_without_resume = False
            saw_progress = False

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
                await self._send_prompt(attempt_prompt)

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
                    if (
                        attempt_session_id
                        and not retried_without_resume
                        and not saw_progress
                        and _is_resume_stream_disconnect(event.error)
                    ):
                        logger.warning(
                            "Codex session %s could not resume after WebSocket retries; "
                            "rolling over to a text-only recovery session",
                            attempt_session_id,
                        )
                        attempt_prompt = _build_resume_recovery_prompt(
                            prompt, attempt_session_id, env
                        )
                        should_retry_without_resume = True
                        retried_without_resume = True
                        break
                    if event.text or event.tool_use is not None or event.tool_result_id:
                        saw_progress = True
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
        append_system_prompt: str | None = None,
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
            append_system_prompt=(
                append_system_prompt
                if append_system_prompt is not None
                else self.append_system_prompt
            ),
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
        if self.append_system_prompt:
            encoded_prompt = json.dumps(self.append_system_prompt, ensure_ascii=False)
            args.extend(["-c", f"developer_instructions={encoded_prompt}"])

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
