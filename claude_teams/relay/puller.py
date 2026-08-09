"""The session host's half: reach out, take work, never listen.

This is the loop that restores the Discord property. It opens no port. It polls
a queue outbound, hands each activity to the same handler the inline endpoint
would have called, and acknowledges only after the handler returns. Replies go
straight to the Bot Connector, also outbound.

Three behaviours matter more than the polling:

**Acknowledge after, not before.** The queue is at-least-once precisely because
this loop can die mid-handler, and a user's message that vanishes because a
process restarted is indistinguishable from a bot that ignored them.

**Duplicates are expected, so they are filtered.** At-least-once means the same
activity can arrive twice — after a lease expiry, a redeploy, a slow handler.
Running a session twice for one message is worse than the crash that caused it,
so the loop remembers the activity ids it has completed.

**A poison message is dropped, loudly, and only after it has proved itself
poison.** An activity that fails every time would otherwise be retried until
the end of time, and the *next* message never gets processed. After a bounded
number of deliveries it is acknowledged and logged as dropped — with its id, so
the loss is a fact someone can look up rather than a gap.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from ..activity import InboundActivity, parse_activity
from .envelope import Envelope
from .queue import ActivityQueue, QueuedItem

logger = logging.getLogger(__name__)

__all__ = ["ActivityPuller"]

Handler = Callable[[InboundActivity], Awaitable[None]]

#: How many completed activity ids to remember. Large enough that a redelivery
#: minutes later is still recognised, small enough to be free.
DEFAULT_SEEN_CAPACITY = 2048

#: Deliveries an activity gets before it is treated as poison. Three is enough
#: to ride out a restart and a transient failure without letting one bad
#: message block the queue forever.
DEFAULT_MAX_DELIVERIES = 3

#: Seconds to wait after an error before polling again, so a queue outage does
#: not become a tight loop against it.
DEFAULT_ERROR_BACKOFF = 5.0

#: Seconds to pause when a poll returns nothing. A queue that honours the long
#: poll never reaches this; one that answers "nothing" instantly would turn
#: this loop into a spin against it. Preventing that is this loop's job, not
#: the queue's — this is the thing that would burn the CPU.
DEFAULT_IDLE_PAUSE = 1.0


class ActivityPuller:
    """Polls the relay queue and drives the handler. Listens on nothing."""

    def __init__(
        self,
        queue: ActivityQueue,
        handler: Handler,
        *,
        on_service_url: Callable[[str, str], None] | None = None,
        max_items: int = 8,
        wait_seconds: float = 20.0,
        max_deliveries: int = DEFAULT_MAX_DELIVERIES,
        seen_capacity: int = DEFAULT_SEEN_CAPACITY,
        error_backoff: float = DEFAULT_ERROR_BACKOFF,
        idle_pause: float = DEFAULT_IDLE_PAUSE,
        sleep: Any = asyncio.sleep,
    ) -> None:
        """
        Args:
            on_service_url: Called with ``(conversation_id, service_url)`` for
                every activity, so ``TeamsFrontend`` learns where a
                conversation is served from — the one piece of addressing the
                ledger does not carry.
        """
        self._queue = queue
        self._handler = handler
        self._on_service_url = on_service_url
        self._max_items = max_items
        self._wait_seconds = wait_seconds
        self._max_deliveries = max_deliveries
        self._error_backoff = error_backoff
        self._idle_pause = idle_pause
        self._sleep = sleep
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_capacity = seen_capacity
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Begin polling in the background."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self.run())

    async def close(self) -> None:
        """Stop polling. Any in-flight item is left unacknowledged, so it comes
        back — a shutdown must not silently consume a user's message."""
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def run(self) -> None:
        while self._running:
            try:
                items = await self._queue.pull(
                    max_items=self._max_items, wait_seconds=self._wait_seconds
                )
            except Exception:
                logger.exception("Failed to poll the Teams relay queue")
                await self._sleep(self._error_backoff)
                continue
            if not items:
                await self._sleep(self._idle_pause)
                continue
            for item in items:
                if not self._running:
                    return
                await self.handle_one(item)

    async def handle_one(self, item: QueuedItem) -> None:
        """Process one queued item, acknowledging only when it is truly done."""
        try:
            envelope = Envelope.decode(item.text)
        except ValueError as exc:
            # Unreadable now means unreadable next time. Retrying it would
            # block the queue on a message nothing can ever consume.
            logger.error("Dropping an unreadable relay message: %s", exc)
            await self._ack(item)
            return

        try:
            activity = parse_activity(envelope.activity)
        except ValueError as exc:
            logger.error("Dropping a malformed relayed activity: %s", exc)
            await self._ack(item)
            return

        if activity.id and activity.id in self._seen:
            # A redelivery of something already handled. Acknowledge it — the
            # work is done — but do not do the work again.
            logger.info("Skipping a Teams activity already handled: %s", activity.id)
            await self._ack(item)
            return

        if item.delivery_count > self._max_deliveries:
            logger.error(
                "Dropping a Teams activity after %s deliveries (id=%s, conversation=%s)",
                item.delivery_count,
                activity.id or "?",
                envelope.conversation_id or "?",
            )
            await self._ack(item)
            return

        if self._on_service_url is not None and envelope.conversation_id:
            self._on_service_url(envelope.conversation_id, envelope.service_url)

        try:
            await self._handler(activity)
        except Exception:
            # Leave it unacknowledged: the lease expires and it comes back,
            # up to max_deliveries. A handler that fails once often succeeds
            # on the next attempt, and losing the message is not recoverable.
            logger.exception("Handler failed for a relayed Teams activity")
            return

        if activity.id:
            self._remember(activity.id)
        await self._ack(item)

    # -- internals ---------------------------------------------------------

    def _remember(self, activity_id: str) -> None:
        self._seen[activity_id] = None
        while len(self._seen) > self._seen_capacity:
            self._seen.popitem(last=False)

    async def _ack(self, item: QueuedItem) -> None:
        try:
            await self._queue.ack(item)
        except Exception:
            # The work is done; a failed delete only means it will come back
            # and be recognised as a duplicate. Worth a log, not a crash.
            logger.warning("Could not acknowledge a relay message", exc_info=True)
