"""Frontend-neutral projection of backend stream events.

The projector decides *what* a frontend may present.  Discord, Slack, and other
adapters remain responsible for *how* a projection is rendered (send, edit,
buttons, and chunking).
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .types import MessageType, StreamEvent


class PresentationMode(str, Enum):
    """Assistant-text delivery policy.

    ``STREAM`` preserves the existing behavior: assistant text is visible as it
    arrives. ``FINAL`` suppresses intermediate commentary and emits text only
    when the backend reaches a successful terminal result.
    """

    STREAM = "stream"
    FINAL = "final"


@dataclass(frozen=True)
class PresentationPolicy:
    """Frontend-neutral choices for projecting one backend turn."""

    mode: PresentationMode = PresentationMode.STREAM


@dataclass(frozen=True)
class TextUpdate:
    """Assistant text that a streaming frontend may upsert in place."""

    text: str


@dataclass(frozen=True)
class InteractiveProjection:
    """An interactive request that must be presented without waiting for RESULT."""

    event: StreamEvent


@dataclass(frozen=True)
class FinalResult:
    """The single successful terminal answer for a turn."""

    text: str


@dataclass(frozen=True)
class ErrorProjection:
    """A backend error that must be presented immediately."""

    error: str
    event: StreamEvent


Projection: TypeAlias = TextUpdate | InteractiveProjection | FinalResult | ErrorProjection


class StreamProjector:
    """Stateful reducer from backend ``StreamEvent`` values to UI projections."""

    def __init__(
        self,
        policy: PresentationPolicy | PresentationMode | None = None,
    ) -> None:
        if policy is None:
            policy = PresentationPolicy()
        self.policy = (
            policy if isinstance(policy, PresentationPolicy) else PresentationPolicy(mode=policy)
        )
        self.mode = self.policy.mode
        self._latest_text = ""
        self._terminal = False

    def project(self, event: StreamEvent) -> tuple[Projection, ...]:
        """Project one stream event, omitting empty and post-terminal output."""
        if self._terminal:
            return ()

        if event.error:
            self._terminal = True
            return (ErrorProjection(event.error, event),)

        projected: list[Projection] = []
        if _is_interactive(event):
            projected.append(InteractiveProjection(event))

        if event.message_type == MessageType.ASSISTANT and _has_text(event.text):
            assert event.text is not None
            self._latest_text = event.text
            if self.mode == PresentationMode.STREAM:
                projected.append(TextUpdate(event.text))

        if event.message_type == MessageType.RESULT or event.is_complete:
            self._terminal = True
            final_text = event.text if _has_text(event.text) else self._latest_text
            if _has_text(final_text):
                assert final_text is not None
                projected.append(FinalResult(final_text))

        return tuple(projected)


async def project_stream(
    events: AsyncIterable[StreamEvent],
    policy: PresentationPolicy | None = None,
) -> AsyncIterator[Projection]:
    """Project a backend event stream for consumption by any frontend adapter."""
    projector = StreamProjector(policy)
    async for event in events:
        for projection in projector.project(event):
            yield projection


def _has_text(text: str | None) -> bool:
    return text is not None and bool(text.strip())


def _is_interactive(event: StreamEvent) -> bool:
    return bool(
        event.permission_request is not None
        or event.elicitation is not None
        or event.ask_questions
        or event.is_plan_approval
    )
