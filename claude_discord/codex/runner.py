"""Codex CLI runner.

Spawns ``codex exec --json`` as an async subprocess and translates the small
subset of Codex events that the shared Discord execution path needs in v1:

- ``thread.started`` -> shared SYSTEM event carrying the persisted session id
- ``turn.failed`` -> shared RESULT error event
- successful completion -> shared RESULT text event read from
  ``--output-last-message``
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import shutil
import signal
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

from ..claude.types import ImageData, MessageType, StreamEvent

__all__ = ["CodexRunner"]

logger = logging.getLogger(__name__)

_UNSET = object()
_IMAGE_SUFFIX = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class CodexRunner:
    """Manages Codex CLI subprocess execution."""

    # Environment variables that must never leak to the CLI subprocess.
    _STRIPPED_ENV_KEYS = frozenset(
        {
            "CLAUDECODE",
            "DISCORD_BOT_TOKEN",
            "DISCORD_TOKEN",
            "API_SECRET_KEY",
        }
    )

    def __init__(
        self,
        command: str = "codex",
        model: str = "",
        permission_mode: str = "full-auto",
        working_dir: str | None = None,
        timeout_seconds: int = 300,
        allowed_tools: list[str] | None = None,
        dangerously_skip_permissions: bool = False,
        api_port: int | None = None,
        api_secret: str | None = None,
        thread_id: int | None = None,
        append_system_prompt: str | None = None,
        images: list[ImageData] | None = None,
        sandbox_mode: str = "workspace-write",
    ) -> None:
        self.command = command
        self.model = model
        self.permission_mode = permission_mode
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self.allowed_tools = allowed_tools
        self.dangerously_skip_permissions = dangerously_skip_permissions
        self.api_port = api_port
        self.api_secret = api_secret
        self.thread_id = thread_id
        self.append_system_prompt = append_system_prompt
        self.images = images
        self.sandbox_mode = sandbox_mode
        self._process: asyncio.subprocess.Process | None = None

    def clone(
        self,
        thread_id: int | None = None,
        model: str | None = None,
        append_system_prompt: str | None = None,
        allowed_tools: list[str] | None | object = _UNSET,
        fork_session: bool = False,
        working_dir: str | None | object = _UNSET,
    ) -> CodexRunner:
        """Create a fresh runner with the same configuration but no active process."""
        del fork_session  # Codex v1 does not support Claude's fork-session flag.

        return CodexRunner(
            command=self.command,
            model=model if model is not None else self.model,
            permission_mode=self.permission_mode,
            working_dir=(
                self.working_dir if working_dir is _UNSET else working_dir  # type: ignore[arg-type]
            ),
            timeout_seconds=self.timeout_seconds,
            allowed_tools=(
                self.allowed_tools if allowed_tools is _UNSET else allowed_tools  # type: ignore[arg-type]
            ),
            dangerously_skip_permissions=self.dangerously_skip_permissions,
            api_port=self.api_port,
            api_secret=self.api_secret,
            thread_id=thread_id if thread_id is not None else self.thread_id,
            append_system_prompt=(
                append_system_prompt
                if append_system_prompt is not None
                else self.append_system_prompt
            ),
            images=self.images,
            sandbox_mode=self.sandbox_mode,
        )

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run Codex CLI and yield shared stream events."""
        output_fd, output_name = tempfile.mkstemp(prefix="ccdb-codex-last-", suffix=".txt")
        os.close(output_fd)
        output_path = Path(output_name)
        image_dir: Path | None = None

        try:
            image_paths, image_dir = self._prepare_image_paths()
            args = self._build_args(
                output_path=output_path,
                session_id=session_id,
                image_paths=image_paths,
            )
            env = self._build_env()
            cwd = self.working_dir or os.getcwd()

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

            if self._process.stdin is not None:
                await self._send_prompt(prompt)

            try:
                async for event in self._read_stream(output_path):
                    yield event
            except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041
                logger.warning("Codex CLI timed out after %ds", self.timeout_seconds)
                yield StreamEvent(
                    raw={},
                    message_type=MessageType.RESULT,
                    is_complete=True,
                    error=f"Timed out after {self.timeout_seconds} seconds",
                )
        finally:
            await self._cleanup()
            with contextlib.suppress(OSError):
                output_path.unlink()
            if image_dir is not None:
                shutil.rmtree(image_dir, ignore_errors=True)

    async def interrupt(self) -> None:
        """Gracefully interrupt the active Codex process."""
        if self._process is None or self._process.returncode is not None:
            return

        with contextlib.suppress(ProcessLookupError):
            self._process.send_signal(signal.SIGINT)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._process.wait(), timeout=5)

    async def kill(self) -> None:
        """Force-kill the active Codex process."""
        if self._process is None or self._process.returncode is not None:
            return

        with contextlib.suppress(ProcessLookupError):
            self._process.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._process.wait(), timeout=5)

    async def inject_tool_result(self, request_id: str, data: dict) -> None:
        """Compatibility no-op for the shared runner protocol.

        Codex v1 support does not translate interactive permission or elicitation
        events into the shared path, so there is nothing to inject back.
        """
        del request_id, data
        logger.debug("CodexRunner.inject_tool_result() is a no-op in v1")

    def _build_args(
        self,
        *,
        output_path: Path,
        session_id: str | None,
        image_paths: list[str] | None = None,
    ) -> list[str]:
        """Build command-line arguments for the Codex CLI."""
        args = [self.command, "exec"]
        if session_id:
            args.append("resume")

        args.extend(
            [
                "--json",
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
            ]
        )

        if self.model:
            args.extend(["--model", self.model])

        if self.working_dir:
            args.extend(["--cd", self.working_dir])

        if self.dangerously_skip_permissions:
            args.append("--dangerously-bypass-approvals-and-sandbox")
        elif self.permission_mode == "full-auto":
            args.append("--full-auto")
        elif self.sandbox_mode:
            args.extend(["--sandbox", self.sandbox_mode])

        for image_path in image_paths or []:
            args.extend(["--image", image_path])

        # Prompt is sent via stdin using the "-" sentinel so user text never
        # becomes part of option parsing.
        args.append("--")
        if session_id:
            args.append(session_id)
        args.append("-")

        return args

    def _build_env(self) -> dict[str, str]:
        """Build environment variables for the subprocess."""
        env = {k: v for k, v in os.environ.items() if k not in self._STRIPPED_ENV_KEYS}
        overlay_path = os.environ.get("CCDB_CLI_ENV_FILE")
        if overlay_path:
            try:
                for line in Path(overlay_path).read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env[key] = value
            except OSError:
                logger.debug("CLI env overlay file not found: %s", overlay_path)
        if self.api_port is not None:
            env["CCDB_API_URL"] = f"http://127.0.0.1:{self.api_port}"
        if self.api_secret is not None:
            env["CCDB_API_SECRET"] = self.api_secret
        if self.thread_id is not None:
            env["DISCORD_THREAD_ID"] = str(self.thread_id)
        return env

    async def _send_prompt(self, prompt: str) -> None:
        """Write the composed prompt to stdin and close the pipe."""
        assert self._process is not None and self._process.stdin is not None

        final_prompt = self._compose_prompt(prompt)
        self._process.stdin.write(final_prompt.encode("utf-8"))
        await self._process.stdin.drain()
        self._process.stdin.close()

    def _compose_prompt(self, prompt: str) -> str:
        """Combine provider-agnostic injected context with the user prompt."""
        if self.append_system_prompt and prompt:
            return f"{self.append_system_prompt}\n\n---\n\n{prompt}"
        if self.append_system_prompt:
            return self.append_system_prompt
        return prompt

    def _prepare_image_paths(self) -> tuple[list[str], Path | None]:
        """Decode base64 image payloads into temp files for ``codex --image``."""
        if not self.images:
            return [], None

        temp_dir = Path(tempfile.mkdtemp(prefix="ccdb-codex-images-"))
        paths: list[str] = []

        for idx, image in enumerate(self.images, start=1):
            suffix = _IMAGE_SUFFIX.get(image.media_type, ".bin")
            path = temp_dir / f"image-{idx}{suffix}"
            path.write_bytes(base64.b64decode(image.data))
            paths.append(str(path))

        return paths, temp_dir

    async def _read_stream(self, output_path: Path) -> AsyncGenerator[StreamEvent, None]:
        """Read Codex JSONL output and translate it into shared StreamEvents."""
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Process not started")

        saw_terminal = False
        last_error: str | None = None

        while True:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self.timeout_seconds,
            )
            if not line:
                break

            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded or not decoded.startswith("{"):
                continue

            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(decoded)
                event_type = payload.get("type")

                if event_type == "thread.started":
                    thread_id = payload.get("thread_id")
                    if thread_id:
                        yield StreamEvent(
                            raw=payload,
                            message_type=MessageType.SYSTEM,
                            session_id=thread_id,
                        )
                    continue

                if event_type == "error":
                    last_error = payload.get("message") or last_error
                    continue

                if event_type == "turn.failed":
                    error = payload.get("error", {}).get("message") or last_error or "Codex failed"
                    saw_terminal = True
                    yield StreamEvent(
                        raw=payload,
                        message_type=MessageType.RESULT,
                        is_complete=True,
                        error=error,
                    )
                    return

        if self._process.returncode is None:
            await asyncio.wait_for(self._process.wait(), timeout=10)

        if self._process.returncode is not None and self._process.returncode > 0:
            stderr_text = ""
            if self._process.stderr is not None:
                stderr_data = await self._process.stderr.read()
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
            error = last_error or stderr_text or f"CLI exited with code {self._process.returncode}"
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                error=error,
            )
            return

        if saw_terminal:
            return

        last_message = self._read_last_message(output_path)
        if last_message is not None:
            yield StreamEvent(
                raw={},
                message_type=MessageType.RESULT,
                is_complete=True,
                text=last_message,
            )
            return

        yield StreamEvent(
            raw={},
            message_type=MessageType.RESULT,
            is_complete=True,
            error="Codex completed without a final message",
        )

    def _read_last_message(self, output_path: Path) -> str | None:
        """Read the agent's final message written by ``--output-last-message``."""
        with contextlib.suppress(OSError):
            text = output_path.read_text(encoding="utf-8").strip()
            return text or None
        return None

    async def _cleanup(self) -> None:
        """Ensure the subprocess is not left running and forget it."""
        if self._process is not None and self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()
            with contextlib.suppress(Exception):
                await self._process.wait()
        self._process = None
