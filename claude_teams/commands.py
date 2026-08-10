"""Text commands, because Teams does not have slash commands for bots.

Discord registers `/model` with the platform and gets autocomplete, argument
validation and a UI. Teams offers none of that to a bot: the manifest's
``commandLists`` only *pre-fills the compose box*, so what arrives is an
ordinary message whose text happens to start with a slash. The router is
therefore not a convenience — it is the whole command surface.

Two rules keep it from eating things it should not:

**Only registered names are commands.** A message starting ``/tmp/build.log is
missing`` is a sentence about a path, not an invocation of a ``tmp`` command.
Parsing first and dispatching later would silently swallow it; here an
unrecognised name is simply not a command and the text goes to the session
unchanged.

**The registry is also what the manifest advertises.** The command menu Teams
shows and the commands this process answers come from one list, so they cannot
drift into disagreeing — which is the failure mode of writing the menu by hand:
a documented command that does nothing.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEFAULT_COMMANDS",
    "Command",
    "CommandRouter",
    "ParsedCommand",
    "default_menu",
    "parse_command",
]

#: The commands a Teams deployment advertises out of the box. One list feeds
#: both the manifest's menu and the router a deployment builds, so the menu
#: cannot advertise something nothing answers.
DEFAULT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("help", "Show what this bot can do"),
    ("model", "Switch the model for this conversation"),
    ("sessions", "List the sessions running right now"),
    ("stop", "Interrupt the session in this conversation"),
)


def default_menu() -> list[dict[str, str]]:
    """The ``commandLists`` entries for a deployment that registers the defaults."""
    return [{"title": name, "description": description} for name, description in DEFAULT_COMMANDS]


#: A leading slash, a name, and the rest. The name is deliberately narrow: no
#: dots or slashes, so a path cannot be mistaken for a command name before the
#: registry is even consulted.
_COMMAND = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)

CommandHandler = Callable[["ParsedCommand"], Awaitable[str | None]]


@dataclass(frozen=True)
class ParsedCommand:
    """A recognised command and whatever followed it."""

    name: str
    args: str
    #: The activity it arrived on, so a handler can answer in the right place.
    activity: Any = None

    def with_activity(self, activity: Any) -> ParsedCommand:
        return ParsedCommand(name=self.name, args=self.args, activity=activity)


@dataclass(frozen=True)
class Command:
    """One command, as both a handler and a menu entry."""

    name: str
    description: str
    handler: CommandHandler


def parse_command(text: str) -> ParsedCommand | None:
    """Split *text* into a command and its arguments, if it looks like one.

    Shape only — whether the name means anything is the router's business.
    Returns ``None`` for ordinary text.
    """
    if not text:
        return None
    match = _COMMAND.match(text.strip())
    if match is None:
        return None
    return ParsedCommand(name=match.group(1).lower(), args=(match.group(2) or "").strip())


class CommandRouter:
    """The commands a deployment answers, and the menu it advertises."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, name: str, description: str, handler: CommandHandler) -> None:
        key = name.lstrip("/").lower()
        if not key:
            raise ValueError("a command needs a name")
        if key in self._commands:
            raise ValueError(f"command {key!r} is already registered")
        self._commands[key] = Command(name=key, description=description, handler=handler)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._commands))

    def menu(self) -> list[dict[str, str]]:
        """The ``commandLists`` entries for the manifest.

        Generated from the same registry that dispatches, so the menu cannot
        advertise a command nothing answers.
        """
        return [
            {"title": command.name, "description": command.description}
            for command in sorted(self._commands.values(), key=lambda c: c.name)
        ]

    async def dispatch(self, text: str, activity: Any = None) -> str | None:
        """Run the command in *text*, if it is one this router knows.

        Returns the handler's reply, or ``None`` when the text was not a
        command — which the caller must treat as "pass it to the session", not
        as "the command produced no output".
        """
        parsed = parse_command(text)
        if parsed is None:
            return None
        command = self._commands.get(parsed.name)
        if command is None:
            return None
        return await command.handler(parsed.with_activity(activity))

    def is_command(self, text: str) -> bool:
        """Whether *text* would dispatch. Lets a caller decide before running."""
        parsed = parse_command(text)
        return parsed is not None and parsed.name in self._commands
