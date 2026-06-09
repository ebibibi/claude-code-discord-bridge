"""Abstract base class for AI agent runners.

Defines the interface that all runner backends (Claude Code CLI, Codex, etc.)
must implement. Consumer code (Cogs, views, scheduler) depends only on this
interface, making the backend swappable without touching downstream code.

Created: 2026-06-09 — 6/15 harness-swap preparation.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from .types import StreamEvent


class BaseRunner(ABC):
    """Abstract interface for AI agent execution backends.

    Any runner backend must implement these 4 methods:
      - run()                  → execute a prompt and stream events
      - inject_tool_result()   → respond to permission/elicitation requests
      - interrupt() / kill()   → graceful / forced stop
      - clone()                → create a fresh instance with the same config

    All runners yield StreamEvent objects, keeping the downstream Cog layer
    completely agnostic about which backend is in use.
    """

    @abstractmethod
    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Execute a prompt and yield stream events.

        Args:
            prompt: The user's message/prompt.
            session_id: Optional session ID to resume a previous conversation.

        Yields:
            StreamEvent objects representing the agent's output.
        """
        ...  # pragma: no cover
        # Make this an async generator at the type level
        if False:  # noqa: SIM223 — trick for abstract async generator typing
            yield  # type: ignore[misc]

    @abstractmethod
    async def inject_tool_result(self, request_id: str, data: dict) -> None:
        """Send a permission/elicitation response to the running agent.

        Args:
            request_id: The request_id from the PermissionRequest or ElicitationRequest.
            data: The response payload.
        """
        ...

    @abstractmethod
    async def interrupt(self) -> None:
        """Gracefully interrupt the running agent (like Ctrl+C)."""
        ...

    @abstractmethod
    async def kill(self) -> None:
        """Force-stop the running agent."""
        ...

    @abstractmethod
    def clone(
        self,
        thread_id: int | None = None,
        model: str | None = None,
        append_system_prompt: str | None = None,
    ) -> Self:
        """Create a fresh runner with the same config but no active process.

        Args:
            thread_id: Discord thread ID override.
            model: Model override for this clone.
            append_system_prompt: System prompt append override.

        Returns:
            A new runner instance of the same type.
        """
        ...
