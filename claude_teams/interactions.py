"""Deciding whether an inbound card action may answer a waiting prompt.

An Adaptive Card action arrives as an ordinary activity carrying whatever
``data`` the client sent. The Bot Connector proves *a Teams user sent it*; it
proves nothing about the payload matching a card this process posted. So every
field here is untrusted input — and the prompts being answered include
tool-permission requests, where "the user allowed it" is the most valuable
sentence anyone could forge.

The rules, in the order they matter:

1. **The conversation must match.** A prompt is bound to the conversation it
   was posted in. Without this, someone who learns a prompt id can approve a
   tool run in a conversation they are not part of, and the session sees an
   ordinary approval with nothing odd about it.
2. **The value must have been offered.** Otherwise a crafted action returns
   any string as "what the user chose".
3. **Once only.** A resolved or cancelled prompt is gone, so a replayed action
   cannot answer the *next* prompt that happens to reuse an id, and a
   re-pressed Stop cannot interrupt the session after this one.
4. **Only declared keys come back from a form.** A card submit merges every
   input on the card into the payload, including anything added to it.

Cancellation resolves the waiter with ``None`` rather than leaving it pending:
a caller blocked on a prompt nobody can answer any more is a session that never
finishes.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["InteractionRegistry", "PendingInteraction"]

logger = logging.getLogger(__name__)

#: The keys ccdb puts into an action's ``data``. Namespaced so they cannot
#: collide with a form field's own key.
PROMPT_ID_KEY = "ccdb_prompt"
CHOICE_VALUE_KEY = "ccdb_value"
FREE_TEXT_KEY = "ccdb_text"

#: Reserved keys are stripped from form answers rather than returned as
#: fields, so a form can safely declare a key of its own without clashing.
_RESERVED = frozenset({PROMPT_ID_KEY, CHOICE_VALUE_KEY, FREE_TEXT_KEY})

InteractionKind = Literal["choice", "form", "stop"]

#: Choice values arrive from ``Input.ChoiceSet`` as a comma-joined string.
_MULTI_SEPARATOR = ","


@dataclass
class PendingInteraction:
    """One prompt or control waiting to be answered."""

    id: str
    conversation_id: str
    kind: InteractionKind
    future: asyncio.Future[Any]
    values: frozenset[str] = field(default_factory=frozenset)
    keys: tuple[str, ...] = ()
    multi_select: bool = False
    allow_free_text: bool = False
    on_stop: Callable[[], Awaitable[None]] | None = None


class InteractionRegistry:
    """The set of prompts a deployment is currently waiting on."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingInteraction] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # -- registration ------------------------------------------------------

    def register_choice(
        self,
        conversation_id: str,
        *,
        values: Sequence[str],
        multi_select: bool,
        allow_free_text: bool = False,
    ) -> PendingInteraction:
        if not values and not allow_free_text:
            raise ValueError("a choice with no values and no free text is unanswerable")
        return self._register(
            conversation_id,
            "choice",
            values=frozenset(values),
            multi_select=multi_select,
            allow_free_text=allow_free_text,
        )

    def register_form(self, conversation_id: str, *, keys: Sequence[str]) -> PendingInteraction:
        if not keys:
            raise ValueError("a form with no fields is unanswerable")
        return self._register(conversation_id, "form", keys=tuple(keys))

    def register_stop(
        self, conversation_id: str, on_stop: Callable[[], Awaitable[None]]
    ) -> PendingInteraction:
        return self._register(conversation_id, "stop", on_stop=on_stop)

    def _register(
        self, conversation_id: str, kind: InteractionKind, **extra: Any
    ) -> PendingInteraction:
        if not conversation_id:
            raise ValueError("conversation_id must not be empty")
        # Unguessable rather than sequential. The conversation binding is the
        # real control, but an id nobody can enumerate removes the class of
        # attack that starts with guessing one.
        interaction = PendingInteraction(
            id=secrets.token_urlsafe(16),
            conversation_id=conversation_id,
            kind=kind,
            future=asyncio.get_running_loop().create_future(),
            **extra,
        )
        self._pending[interaction.id] = interaction
        return interaction

    # -- resolution --------------------------------------------------------

    def resolve(self, conversation_id: str, data: Any) -> bool:
        """Apply an inbound action's ``data``. Returns whether it was accepted.

        Every refusal is silent to the caller by design: the endpoint answers
        one thing for all of them, because "wrong conversation" and "expired"
        are both free information to whoever is probing.
        """
        if not isinstance(data, dict):
            return False
        prompt_id = data.get(PROMPT_ID_KEY)
        if not isinstance(prompt_id, str) or not prompt_id:
            return False
        interaction = self._pending.get(prompt_id)
        if interaction is None:
            return False
        if interaction.conversation_id != conversation_id:
            logger.warning(
                "Refused a Teams card action for a prompt in another conversation (%s)", prompt_id
            )
            return False

        if interaction.kind == "stop":
            return self._resolve_stop(interaction)
        if interaction.kind == "form":
            return self._resolve_form(interaction, data)
        return self._resolve_choice(interaction, data)

    def cancel(self, prompt_id: str) -> None:
        """Withdraw a prompt, releasing anyone waiting on it with ``None``."""
        interaction = self._pending.pop(prompt_id, None)
        if interaction is not None and not interaction.future.done():
            interaction.future.set_result(None)

    # -- per-kind ----------------------------------------------------------

    def _resolve_choice(self, interaction: PendingInteraction, data: dict[str, Any]) -> bool:
        raw = data.get(CHOICE_VALUE_KEY)
        if isinstance(raw, str) and raw:
            chosen = tuple(part.strip() for part in raw.split(_MULTI_SEPARATOR) if part.strip())
            if not chosen:
                return False
            if not interaction.multi_select and len(chosen) > 1:
                return False
            if not set(chosen) <= interaction.values:
                return False
            return self._settle(interaction, chosen)

        text = data.get(FREE_TEXT_KEY)
        if interaction.allow_free_text and isinstance(text, str) and text.strip():
            return self._settle(interaction, (text.strip(),))
        return False

    def _resolve_form(self, interaction: PendingInteraction, data: dict[str, Any]) -> bool:
        answers = {
            key: _as_text(data[key])
            for key in interaction.keys
            if key in data and key not in _RESERVED and data[key] is not None
        }
        return self._settle(interaction, answers)

    def _resolve_stop(self, interaction: PendingInteraction) -> bool:
        if interaction.on_stop is None:
            return False
        self._pending.pop(interaction.id, None)
        # Fire and forget: an invoke has to be answered promptly, and stopping
        # a session is not something to make the user's client wait on.
        task = asyncio.ensure_future(interaction.on_stop())
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
        if not interaction.future.done():
            interaction.future.set_result(True)
        return True

    def _settle(self, interaction: PendingInteraction, result: Any) -> bool:
        self._pending.pop(interaction.id, None)
        if interaction.future.done():
            return False
        interaction.future.set_result(result)
        return True


def _as_text(value: Any) -> str:
    """Adaptive Card inputs return booleans and numbers as well as strings."""
    return value if isinstance(value, str) else str(value)


def values_of(choices: Iterable[Any]) -> tuple[str, ...]:
    """The ``value`` of each :class:`~claude_code_core.frontend.Choice`."""
    return tuple(choice.value for choice in choices)


#: Strong references to in-flight stop callbacks, so the event loop does not
#: garbage-collect a task nobody is awaiting.
_BACKGROUND: set[asyncio.Task[None]] = set()
