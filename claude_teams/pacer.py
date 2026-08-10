"""Spending a conversation's update budget on the update worth spending it on.

Teams allows 1,800 operations per hour per conversation. A session that shows
what it is doing changes that display far more often — a tool starts, a status
flips, a stream grows — so the interesting question is not "may I update" but
"which of these updates gets a slot".

The answer here is: the newest one *per target*, at most one update per
interval overall. That is different from throttling, which drops updates, and
from queueing, which delivers all of them late. Coalescing delivers the
*current* state on the next slot, which is the only state anyone wants to see.

"Per target" is what makes it usable. A session edits two different messages —
the card showing what it is doing, and the reply it is streaming — and the
budget belongs to the conversation, not to either message. Coalescing on one
key would have a card repaint silently discard a pending stream edit, and the
answer would stop growing on screen for no visible reason.

Four details carry the design:

* **The first update is immediate.** A budget nobody is competing for should
  not cost latency, and an artificial pause before the first sign of life is
  what makes a bot feel dead.
* **A failure clears the slot.** An edit can fail for reasons unrelated to the
  next one. A pacer that stayed "busy" after a failure would take the rest of
  the session's display down with it.
* **Close drops what is pending.** Once the conversation is finished, a queued
  edit would repaint a card the session has already moved past.
* **Targets take turns.** When several are waiting, the one that has been
  waiting longest goes first, so a fast-changing card cannot starve a stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = ["UpdatePacer"]

logger = logging.getLogger(__name__)

Update = Callable[[], Awaitable[None]]


class UpdatePacer:
    """Rate-limits updates to one per interval, keeping only the newest."""

    def __init__(
        self,
        min_interval: float,
        *,
        now: Any = time.monotonic,
        sleep: Any = asyncio.sleep,
    ) -> None:
        """
        Args:
            min_interval: Seconds between updates. Read this from
                ``SurfaceCapabilities.min_update_interval`` rather than
                choosing one — that property already resolves the platform's
                hourly quota against the preferred pace.
            now, sleep: Injected so the behaviour can be tested without
                waiting, and so the tests prove the pacing rather than the
                event loop's timing.
        """
        if min_interval <= 0:
            raise ValueError("min_interval must be positive")
        self._min_interval = min_interval
        self._now = now
        self._sleep = sleep
        self._last_sent: float | None = None
        # Insertion-ordered, so the longest-waiting target goes first.
        self._pending: dict[Any, Update] = {}
        self._timer: asyncio.Task[None] | None = None
        self._closed = False

    async def submit(self, update: Update, *, key: Any = None) -> None:
        """Send *update* now, or hold it as the next one for its target.

        Replaces any update still waiting *for the same key*: it was going to
        be overwritten on screen anyway, and spending a slot on a state nobody
        will ever see is the whole thing this class exists to avoid. A
        different key waits its turn instead of displacing anything.
        """
        if self._closed:
            return
        if self._due():
            await self._run(update)
            return
        self._pending[key] = update
        self._ensure_timer()

    async def flush(self) -> None:
        """Send everything pending immediately, ignoring the interval.

        For the end of a session. The final state of each target is worth a
        slot even when it lands early — a card frozen on "running" after the
        session finished is a lie that stays on screen. Does nothing when
        nothing is pending, so calling it on every path is safe.
        """
        self._cancel_timer()
        pending, self._pending = self._pending, {}
        for update in pending.values():
            await self._run(update)

    async def drain(self) -> None:
        """Wait for a scheduled update to go out. Test and shutdown seam."""
        timer = self._timer
        if timer is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await timer

    async def close(self) -> None:
        """Stop pacing and discard anything still waiting."""
        self._closed = True
        self._pending = {}
        self._cancel_timer()

    # -- internals ---------------------------------------------------------

    def _due(self) -> bool:
        return (
            not self._pending
            and self._timer is None
            and (self._last_sent is None or self._now() - self._last_sent >= self._min_interval)
        )

    async def _run(self, update: Update) -> None:
        # The clock advances even when the call fails: a failing edit still
        # cost a request, and retrying it instantly is how a transient 429
        # becomes a sustained one.
        self._last_sent = self._now()
        try:
            await update()
        except Exception:
            logger.exception("Teams conversation update failed")

    def _ensure_timer(self) -> None:
        if self._timer is None:
            self._timer = asyncio.create_task(self._wait_and_send())

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and not timer.done():
            timer.cancel()

    async def _wait_and_send(self) -> None:
        try:
            remaining = self._min_interval
            if self._last_sent is not None:
                remaining = max(0.0, self._min_interval - (self._now() - self._last_sent))
            if remaining > 0:
                await self._sleep(remaining)
            if self._closed or not self._pending:
                return
            _key, update = next(iter(self._pending.items()))
            del self._pending[_key]
            await self._run(update)
        finally:
            self._timer = None
            # Another target may still be waiting; give it the next slot.
            if self._pending and not self._closed:
                self._ensure_timer()
