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

from claude_code_core.frontend import ChoicePrompt, FormField, FormPrompt, StatusKind

from .interactions import CHOICE_VALUE_KEY, FREE_TEXT_KEY, PROMPT_ID_KEY

__all__ = [
    "ACTION_VERB",
    "ActivityLine",
    "MAX_CARD_BYTES",
    "SessionCard",
    "choice_prompt_card",
    "form_prompt_card",
]

#: Every ccdb action uses one verb. Routing is by prompt id, which is what the
#: registry validates; the verb only tells Teams this is a Universal Action so
#: the press arrives as an ``adaptiveCard/action`` invoke it expects an inline
#: answer to.
ACTION_VERB = "ccdb.action"

#: Above this many choices, buttons stop being usable and become a dropdown.
MAX_CHOICE_BUTTONS = 5

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
    #: When set, the card carries a Stop control carrying this id. Left unset
    #: no action is rendered at all: a control nothing routes shows the user an
    #: error when they press it, which is worse than its absence.
    stop_action_id: str | None = None

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

        actions = (
            [_execute("Stop", {PROMPT_ID_KEY: self.stop_action_id}, style="destructive")]
            if self.stop_action_id
            else []
        )
        attachment = _attachment(blocks, actions)
        # Belt and braces: the per-field clipping above is what normally keeps
        # a card small, but a caller can hand over more activities than
        # expected, and a card Teams refuses is a card that stops updating
        # without saying so.
        while len(json.dumps(attachment).encode()) > MAX_CARD_BYTES and len(blocks) > 1:
            del blocks[1]
            attachment = _attachment(blocks, actions)
        return attachment


def choice_prompt_card(prompt: ChoicePrompt, prompt_id: str) -> dict[str, Any]:
    """Render a :class:`ChoicePrompt` as an answerable card.

    A short list of choices becomes one button each, because a permission
    request answered in one press is the difference between a session that
    flows and one that nags. Longer or multi-select lists become a dropdown —
    a row of fifteen buttons is unusable, and Teams wraps them badly.

    Every action carries the prompt id and the chosen *value*. Neither is
    trusted on the way back: :class:`~claude_teams.interactions.InteractionRegistry`
    checks the conversation and that the value was actually offered.
    """
    blocks: list[dict[str, Any]] = []
    if prompt.header:
        blocks.append(_text(_clip(prompt.header, MAX_TITLE_CHARS), weight="Bolder"))
    blocks.append(_text(prompt.question))

    actions: list[dict[str, Any]] = []
    as_dropdown = prompt.multi_select or len(prompt.choices) > MAX_CHOICE_BUTTONS
    if prompt.choices and as_dropdown:
        blocks.append(
            {
                "type": "Input.ChoiceSet",
                "id": CHOICE_VALUE_KEY,
                "isMultiSelect": prompt.multi_select,
                "style": "compact",
                "choices": [
                    {"title": _clip(c.label, MAX_DETAIL_CHARS), "value": c.value}
                    for c in prompt.choices
                ],
            }
        )
    if prompt.allow_free_text:
        blocks.append(
            {
                "type": "Input.Text",
                "id": FREE_TEXT_KEY,
                "placeholder": "Or type an answer",
                "isMultiline": False,
            }
        )
    if prompt.choices and not as_dropdown:
        actions.extend(
            _execute(
                _clip(c.label, MAX_DETAIL_CHARS),
                {PROMPT_ID_KEY: prompt_id, CHOICE_VALUE_KEY: c.value},
                style=_ACTION_STYLE.get(c.style),
            )
            for c in prompt.choices
        )
    else:
        actions.append(_execute("Submit", {PROMPT_ID_KEY: prompt_id}))
    return _attachment(blocks, actions)


def form_prompt_card(prompt: FormPrompt, prompt_id: str) -> dict[str, Any]:
    """Render a :class:`FormPrompt` as a card with one input per field.

    A card submit merges *every* input into the payload, so the ids here are
    the field keys and the registry returns only the keys it declared —
    anything else on the card, or added to the payload, is dropped.
    """
    blocks: list[dict[str, Any]] = [_text(_clip(prompt.title, MAX_TITLE_CHARS), weight="Bolder")]
    if prompt.description:
        blocks.append(_text(prompt.description))
    for field_spec in prompt.fields:
        blocks.append(_text(_field_label(field_spec), subtle=True, small=True))
        blocks.append(_input(field_spec))
    return _attachment(
        blocks, [_execute(prompt.submit_label or "Submit", {PROMPT_ID_KEY: prompt_id})]
    )


def _field_label(field_spec: FormField) -> str:
    return f"{field_spec.label} *" if field_spec.required else field_spec.label


def _input(field_spec: FormField) -> dict[str, Any]:
    common: dict[str, Any] = {"id": field_spec.key}
    if field_spec.placeholder:
        common["placeholder"] = field_spec.placeholder
    if field_spec.kind == "toggle":
        return {"type": "Input.Toggle", "title": field_spec.label, **common}
    if field_spec.kind == "number":
        return {"type": "Input.Number", **common}
    if field_spec.kind == "choice":
        return {
            "type": "Input.ChoiceSet",
            "style": "compact",
            "choices": [
                {"title": _clip(c.label, MAX_DETAIL_CHARS), "value": c.value}
                for c in field_spec.choices
            ],
            **common,
        }
    return {"type": "Input.Text", "isMultiline": field_spec.kind == "multiline", **common}


def _execute(title: str, data: dict[str, Any], *, style: str | None = None) -> dict[str, Any]:
    action: dict[str, Any] = {
        "type": "Action.Execute",
        "title": title,
        "verb": ACTION_VERB,
        "data": data,
    }
    if style:
        action["style"] = style
    return action


_ACTION_STYLE: dict[str, str] = {"positive": "positive", "destructive": "destructive"}


def _attachment(blocks: list[dict[str, Any]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    content: dict[str, Any] = {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        # 1.5 is what Teams renders today.
        "version": "1.5",
        "body": list(blocks),
    }
    if actions:
        content["actions"] = list(actions)
    return {"contentType": ADAPTIVE_CARD_CONTENT_TYPE, "content": content}


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
