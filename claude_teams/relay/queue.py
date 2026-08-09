"""The queue contract, and an in-memory one for tests.

Three operations, and the shape of them is the design:

``push`` / ``pull`` / ``ack``

**Acknowledgement is separate from delivery**, which makes the transport
at-least-once rather than at-most-once. If the session host dies between
receiving a message and finishing with it, the message comes back. The
alternative — deleting on read — loses a user's message on any crash, and a
lost message in a chat is indistinguishable from a bot that ignored someone.

At-least-once means duplicates are possible, so the *host* must be able to see
one twice without acting twice. :class:`~claude_teams.relay.puller.ActivityPuller`
does that by activity id, and its tests say so.

**Pull takes a wait.** Long polling is what keeps an outbound-only design from
being a busy loop: the host asks for work and the queue holds the request open
until there is some. A queue that cannot wait is still usable — the puller
sleeps instead — but it costs requests for nothing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ["ActivityQueue", "MemoryQueue", "QueuedItem"]


@dataclass
class QueuedItem:
    """One message, plus whatever the queue needs to delete it later.

    ``receipt`` is opaque on purpose: Azure Queue Storage needs a pop receipt,
    a different transport needs something else, and the puller should not have
    to know which.
    """

    text: str
    receipt: Any = None
    #: How many times this item has been delivered, when the queue tracks it.
    #: A message that keeps coming back is a poison message, and a puller that
    #: cannot tell will retry it forever.
    delivery_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


class ActivityQueue(Protocol):
    """Where the receiver puts activities and the session host takes them."""

    async def push(self, text: str) -> None: ...

    async def pull(self, *, max_items: int = 8, wait_seconds: float = 20.0) -> list[QueuedItem]:
        """Take up to *max_items*, waiting up to *wait_seconds* for the first."""
        ...

    async def ack(self, item: QueuedItem) -> None:
        """Delete an item that has been fully handled."""
        ...


class MemoryQueue:
    """An in-process queue with the same semantics, for tests.

    Including the awkward ones: nothing is deleted until ``ack``, an item that
    is pulled and not acked becomes visible again after its lease, and
    ``delivery_count`` grows each time. A fake that only models the happy path
    would let the puller's redelivery handling go untested.
    """

    def __init__(self, *, lease_seconds: float = 30.0, now: Any = None) -> None:
        self._items: list[dict[str, Any]] = []
        self._lease = lease_seconds
        self._now = now or (lambda: asyncio.get_event_loop().time())
        self._sequence = 0

    async def push(self, text: str) -> None:
        self._sequence += 1
        self._items.append({"id": self._sequence, "text": text, "visible_at": 0.0, "deliveries": 0})

    async def pull(self, *, max_items: int = 8, wait_seconds: float = 20.0) -> list[QueuedItem]:
        now = self._now()
        taken: list[QueuedItem] = []
        for row in self._items:
            if len(taken) >= max_items:
                break
            if row["visible_at"] <= now:
                row["visible_at"] = now + self._lease
                row["deliveries"] += 1
                taken.append(
                    QueuedItem(
                        text=row["text"], receipt=row["id"], delivery_count=row["deliveries"]
                    )
                )
        if not taken:
            # Model the long poll rather than returning instantly. A fake that
            # answers "nothing" with no delay turns the puller's loop into a
            # busy spin, which is both untrue to the real queue and a hang.
            await asyncio.sleep(0)
        return taken

    async def ack(self, item: QueuedItem) -> None:
        self._items = [row for row in self._items if row["id"] != item.receipt]

    @property
    def depth(self) -> int:
        """How many messages are still unacknowledged."""
        return len(self._items)

    def expire_leases(self) -> None:
        """Make every leased item visible again — a crash, in one call."""
        for row in self._items:
            row["visible_at"] = 0.0
