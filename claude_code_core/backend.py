"""SessionBackend protocol and factory.

Defines the common interface that all CLI backends (Claude, Codex, etc.)
must satisfy, plus a factory function to instantiate them by name.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .types import ImageData, StreamEvent


@runtime_checkable
class SessionBackend(Protocol):
    """Protocol that all CLI backends must satisfy."""

    command: str
    model: str
    working_dir: str | None
    permission_mode: str
    images: list[ImageData] | None
    api_port: int | None
    timeout_seconds: int
    dangerously_skip_permissions: bool
    allowed_tools: list[str] | None

    def run(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]: ...

    def clone(self, **kwargs: object) -> SessionBackend: ...

    async def interrupt(self) -> None: ...

    async def kill(self) -> None: ...

    async def inject_tool_result(self, request_id: str, data: dict) -> None: ...

    def _build_env(self) -> dict[str, str]: ...


def create_backend(
    *,
    backend: str = "claude",
    model: str,
    **kwargs: object,
) -> SessionBackend:
    """Create a backend runner by name.

    Args:
        backend: "claude" or "codex".
        model: Model identifier (e.g. "sonnet", "o4-mini").
        **kwargs: Forwarded to the runner constructor.
    """
    if backend == "claude":
        from .runner import ClaudeRunner

        return ClaudeRunner(model=model, **kwargs)  # type: ignore[arg-type]

    if backend == "codex":
        from .codex_runner import CodexRunner

        return CodexRunner(model=model, **kwargs)  # type: ignore[arg-type]

    raise ValueError(f"Unknown backend: {backend!r}")
