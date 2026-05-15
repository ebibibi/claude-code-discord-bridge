"""Factory for SessionBackend instances.

Holds the static configuration needed to construct ClaudeRunner or
CodexRunner instances on demand. Used by ClaudeChatCog (and friends)
to spawn a fresh runner per Discord thread whenever the user issues
a chat message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from claude_code_core.backend import create_backend

if TYPE_CHECKING:
    from claude_code_core.backend import SessionBackend

logger = logging.getLogger(__name__)


# Sensible per-backend defaults (mirror the CLIs own defaults so users
# do not need to pick a model just to try a backend).
DEFAULT_MODEL = {"claude": "sonnet", "codex": "gpt-5.4"}
DEFAULT_COMMAND = {"claude": "claude", "codex": "codex"}


class BackendFactory:
    """Builds SessionBackend instances on demand from static configuration."""

    def __init__(
        self,
        *,
        claude_command: str,
        codex_command: str,
        permission_mode: str,
        working_dir: str | None,
        timeout_seconds: int,
        dangerously_skip_permissions: bool,
        allowed_tools: list[str] | None,
        append_system_prompt: str | None,
        effort: str | None,
    ) -> None:
        self.claude_command = claude_command or DEFAULT_COMMAND["claude"]
        self.codex_command = codex_command or DEFAULT_COMMAND["codex"]
        self.permission_mode = permission_mode
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self.dangerously_skip_permissions = dangerously_skip_permissions
        self.allowed_tools = allowed_tools
        self.append_system_prompt = append_system_prompt
        self.effort = effort

    def command_for(self, backend: str) -> str:
        if backend == "claude":
            return self.claude_command
        if backend == "codex":
            return self.codex_command
        raise ValueError(f"Unknown backend: {backend!r}")

    def default_model_for(self, backend: str) -> str:
        return DEFAULT_MODEL.get(backend, DEFAULT_MODEL["claude"])

    def build(
        self,
        *,
        backend: str,
        model: str | None = None,
        thread_id: int | None = None,
    ) -> SessionBackend:
        """Construct a fresh SessionBackend for the given backend/model."""
        chosen_model = model or self.default_model_for(backend)
        command = self.command_for(backend)
        kwargs: dict[str, object] = {
            "command": command,
            "permission_mode": self.permission_mode,
            "working_dir": self.working_dir,
            "timeout_seconds": self.timeout_seconds,
            "dangerously_skip_permissions": self.dangerously_skip_permissions,
            "allowed_tools": self.allowed_tools,
        }
        if thread_id is not None:
            kwargs["thread_id"] = thread_id
        # Only ClaudeRunner accepts these — pass via kwargs and let create_backend
        # forward them; CodexRunner.__init__ swallows unknown kwargs via **_kwargs.
        if self.append_system_prompt is not None:
            kwargs["append_system_prompt"] = self.append_system_prompt
        if self.effort is not None:
            kwargs["effort"] = self.effort
        runner = create_backend(backend=backend, model=chosen_model, **kwargs)
        logger.debug("Built %s runner (model=%s, thread_id=%s)", backend, chosen_model, thread_id)
        return runner
