"""What the user actually said, once the @mention is taken out.

In a Teams channel a message addressed to a bot arrives as
``<at>Relay</at> fix the parser``, with the mention repeated in an ``entities``
array. Both parts matter and they matter differently:

* The **entities** say who was mentioned, by id. That is the only reliable way
  to tell "this was addressed to me" from "someone typed my name" — display
  names are not unique and are not stable.
* The **markup** has to come out of the text before the model sees it, or every
  prompt in a channel begins with a tag the session has to learn to ignore, and
  ``/model opus`` mentioned at the front of a message is not a command any
  parser will recognise.

``InboundMessage`` already draws this distinction — ``raw_text`` is what the
platform delivered and ``text`` is what the model should see — and this module
is what fills the gap between them for Teams.
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_core.frontend import Mention

__all__ = ["mentions_in", "strip_mention_markup", "was_mentioned"]

#: Teams wraps a mention in ``<at>…</at>``. The tag survives into ``text``
#: exactly as typed, including when the display name contains markup-ish
#: characters, so it is matched non-greedily and by tag rather than by name.
_AT_TAG = re.compile(r"<at\b[^>]*>.*?</at>", re.IGNORECASE | re.DOTALL)

_WHITESPACE = re.compile(r"[ \t]+")


def _entities(activity_raw: Any) -> list[dict[str, Any]]:
    entities = activity_raw.get("entities") if isinstance(activity_raw, dict) else None
    if not isinstance(entities, list):
        return []
    return [e for e in entities if isinstance(e, dict) and e.get("type") == "mention"]


def was_mentioned(activity_raw: Any, app_id: str) -> bool:
    """Whether *app_id* is among the message's mentions.

    Matched on id, not display name. Teams prefixes a bot's id with ``28:`` in
    a mention, and a tenant can have two apps with the same name, so comparing
    the visible text would be both wrong and unstable.
    """
    if not app_id:
        return False
    for entity in _entities(activity_raw):
        mentioned = entity.get("mentioned")
        if isinstance(mentioned, dict):
            identifier = mentioned.get("id")
            if isinstance(identifier, str) and identifier.split(":")[-1] == app_id:
                return True
    return False


def mentions_in(activity_raw: Any, *, exclude: str = "") -> tuple[Mention, ...]:
    """Everyone mentioned in the message, optionally minus one id.

    The exclusion is normally the bot itself: a session does not need to be
    told it was addressed, and passing its own mention through would put ccdb
    in the list of people a reply should notify.
    """
    found: list[Mention] = []
    for entity in _entities(activity_raw):
        mentioned = entity.get("mentioned")
        if not isinstance(mentioned, dict):
            continue
        identifier = mentioned.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        if exclude and identifier.split(":")[-1] == exclude:
            continue
        name = mentioned.get("name")
        found.append(
            Mention(
                external_user_id=identifier,
                display_name=name if isinstance(name, str) and name else None,
            )
        )
    return tuple(found)


def strip_mention_markup(text: str) -> str:
    """Remove ``<at>…</at>`` tags and tidy the whitespace they leave.

    Every mention goes, not only the bot's. The tags are markup rather than
    content: a session shown ``<at>Ada</at> can you review`` learns to strip
    them itself, badly, and a command typed after a mention is unparseable
    until they are gone.
    """
    if not text:
        return ""
    cleaned = _AT_TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", cleaned).strip()
