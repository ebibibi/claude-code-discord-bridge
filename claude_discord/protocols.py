"""Shared protocols for cross-Cog coordination.

Protocols use structural subtyping (PEP 544): any Cog that defines the
required attributes satisfies the protocol — no explicit inheritance needed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


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
