"""Shared protocols for cross-Cog coordination.

Protocols use structural subtyping (PEP 544): any Cog that defines the
required attributes satisfies the protocol — no explicit inheritance needed.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable

from .claude.types import ImageData, StreamEvent


@runtime_checkable
class DrainAware(Protocol):
    """A Cog that tracks in-flight work and can report whether it is idle.

    AutoUpgradeCog auto-discovers all DrainAware Cogs registered on the bot
    and waits for every one to reach ``active_count == 0`` before restarting.

    Implementors only need to expose an ``active_count`` int property that
    returns the number of currently running tasks/sessions.
    """

    @property
    def active_count(self) -> int: ...


@runtime_checkable
class AgentRunner(Protocol):
    """Shared runner contract for backend-specific CLI implementations."""

    command: str
    model: str
    working_dir: str | None
    dangerously_skip_permissions: bool
    allowed_tools: list[str] | None
    permission_mode: str
    timeout_seconds: int
    api_port: int | None
    images: list[ImageData] | None

    def clone(
        self,
        thread_id: int | None = None,
        model: str | None = None,
        append_system_prompt: str | None = None,
        allowed_tools: list[str] | None | object = ...,
        fork_session: bool = False,
        working_dir: str | None | object = ...,
    ) -> AgentRunner: ...

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]: ...

    async def interrupt(self) -> None: ...

    async def kill(self) -> None: ...

    async def inject_tool_result(self, request_id: str, data: dict[str, Any]) -> None: ...
