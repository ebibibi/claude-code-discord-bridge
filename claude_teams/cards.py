"""The session card: one message that keeps up to date.

Discord posts an embed per tool call and edits it on completion. That is the
right design *there* — editing is cheap, there is no hourly ceiling, and the
scrollback is the record. Porting it to Teams would be the clearest example of
the mistake this whole abstraction exists to prevent: 1,800 operations per hour
per conversation means a session with a few hundred tool calls would spend its
entire budget on message-shaped noise and then go silent.

So Teams gets one card. A tool starting, a status changing and a tool finishing
are all the same operation — repaint the current state — and three of them
inside one interval cost one slot, not three.

Two limits shape the rendering. Teams refuses a card payload over 28 KB, and
rejection is invisible from the sending side: the update fails, the card
freezes on its last good state, and the session looks stuck. So the activity
list is bounded and long text is truncated *here*, where the reason is written
down, rather than by whatever happens to fit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from claude_code_core.frontend import StatusKind

__all__ = ["ActivityLine", "MAX_CARD_BYTES", "SessionCard"]

ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"

#: Teams' own ceiling on a card payload.
MAX_CARD_BYTES = 28 * 1024

DEFAULT_MAX_ACTIVITIES = 8
MAX_TITLE_CHARS = 200
MAX_DETAIL_CHARS = 120

ActivityState = Literal["running", "done", "failed", "cancelled"]

#: What each state looks like. The marker is what distinguishes a failure from
#: a success at a glance, which is the difference the card most has to carry.
_STATE_MARKER: dict[ActivityState, str] = {
    "running": "▶",
    "done": "✓",
    "failed": "✗",
    "cancelled": "—",
}

#: Human labels for every status. ``StatusKind`` grows over time, and an
#: unmapped member must not render as an empty row, so lookups fall back.
_STATUS_LABEL: dict[StatusKind, str] = {
    StatusKind.THINKING: "Thinking",
    StatusKind.TOOL_READ: "Reading",
    StatusKind.TOOL_EDIT: "Editing",
    StatusKind.TOOL_COMMAND: "Running a command",
    StatusKind.TOOL_WEB: "Fetching from the web",
    StatusKind.TOOL_OTHER: "Working",
    StatusKind.HOOK: "Running a hook",
    StatusKind.COMPACTING: "Compacting the conversation",
    StatusKind.STALLED_SOFT: "Waiting",
    StatusKind.STALLED_HARD: "Stalled",
    StatusKind.DONE: "Done",
    StatusKind.ERROR: "Error",
}


def status_label(status: StatusKind) -> str:
    """A human label for *status*, never empty."""
    return _STATUS_LABEL.get(status, status.value.replace("_", " ").capitalize())


@dataclass(frozen=True)
class ActivityLine:
    """One unit of work as it appears on the card."""

    title: str
    state: ActivityState = "running"
    detail: str | None = None
    result: str | None = None

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("ActivityLine.title must not be empty")

    def render(self) -> str:
        marker = _STATE_MARKER.get(self.state, "•")
        tail = self.result or self.detail
        line = f"{marker} {_clip(self.title, MAX_TITLE_CHARS)}"
        return f"{line} — {_clip(tail, MAX_DETAIL_CHARS)}" if tail else line


@dataclass(frozen=True)
class SessionCard:
    """The current state of a session, as one Adaptive Card."""

    title: str
    status: StatusKind | None = None
    activities: tuple[ActivityLine, ...] = field(default_factory=tuple)
    footer: str | None = None
    max_activities: int = DEFAULT_MAX_ACTIVITIES

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("SessionCard.title must not be empty")
        if self.max_activities <= 0:
            raise ValueError("max_activities must be positive")

    def to_attachment(self) -> dict[str, Any]:
        """Render as a Bot Framework attachment, bounded to Teams' size limit."""
        activities = self.activities[-self.max_activities :]
        blocks: list[dict[str, Any]] = [
            _text(_clip(self.title, MAX_TITLE_CHARS), weight="Bolder", size="Medium")
        ]
        if self.status is not None:
            blocks.append(_text(status_label(self.status), subtle=True))
        blocks.extend(_text(line.render(), font="Monospace", small=True) for line in activities)
        if self.footer:
            blocks.append(_text(_clip(self.footer, MAX_DETAIL_CHARS), subtle=True, small=True))

        attachment = _attachment(blocks)
        # Belt and braces: the per-field clipping above is what normally keeps
        # a card small, but a caller can hand over more activities than
        # expected, and a card Teams refuses is a card that stops updating
        # without saying so.
        while len(json.dumps(attachment).encode()) > MAX_CARD_BYTES and len(blocks) > 1:
            del blocks[1]
            attachment = _attachment(blocks)
        return attachment


def _attachment(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contentType": ADAPTIVE_CARD_CONTENT_TYPE,
        "content": {
            "$schema": ADAPTIVE_CARD_SCHEMA,
            "type": "AdaptiveCard",
            # 1.5 is what Teams renders today. No actions are declared yet:
            # an Action.Execute that nothing routes shows the user an error
            # when they press it, which is worse than no control at all. The
            # Stop control arrives with the invoke handler that can answer it.
            "version": "1.5",
            "body": list(blocks),
        },
    }


def _text(
    text: str,
    *,
    weight: str | None = None,
    size: str | None = None,
    subtle: bool = False,
    small: bool = False,
    font: str | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
    if weight:
        block["weight"] = weight
    if size:
        block["size"] = size
    if small:
        block["size"] = "Small"
    if subtle:
        block["isSubtle"] = True
    if font:
        block["fontType"] = font
    return block


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
