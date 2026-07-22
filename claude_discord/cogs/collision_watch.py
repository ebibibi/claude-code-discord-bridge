"""CollisionWatchCog — notice when two live sessions edit the same files.

The lounge depends on sessions announcing themselves; a session that forgets is
invisible, and those are exactly the ones that collide.  This Cog watches what
sessions actually write (recorded by ``EventProcessor`` into a
``FileActivityTracker``) and speaks up when two live threads touch the same
file.

Delivery is deliberately cheap:

* a line in the **AI Lounge**, which is injected into every session's next turn
  at no token cost and with no interruption, and
* a message in **each colliding thread**, so the human watching sees it now.

It never relays into a running session — that would preempt a turn on a mere
suspicion.  Escalating is the sessions' decision, using the relay endpoint.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from ..collision import (
    AlertLedger,
    Collision,
    FileActivityTracker,
    build_collision_notice,
    build_lounge_notice,
    find_collisions,
)

if TYPE_CHECKING:
    from ..concurrency import SessionRegistry
    from ..database.lounge_repo import LoungeRepository

logger = logging.getLogger(__name__)

# Fast enough to catch an overlap while both sessions are still working, slow
# enough to stay invisible in the bot's workload.
POLL_INTERVAL_SECONDS = 60


class CollisionWatchCog(commands.Cog):
    """Poll the activity tracker and announce collisions between live sessions."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        tracker: FileActivityTracker | None = None,
        registry: SessionRegistry | None = None,
        lounge_repo: LoungeRepository | None = None,
        lounge_channel_id: int | None = None,
    ) -> None:
        self.bot = bot
        self._tracker = tracker or getattr(bot, "file_activity", None)
        self._registry = registry or getattr(bot, "session_registry", None)
        self._lounge_repo = lounge_repo
        self._lounge_channel_id = lounge_channel_id
        self._ledger = AlertLedger()
        if self._tracker is not None and self._registry is not None:
            self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def watch(self) -> None:
        """One detection pass. Never raises — a watcher must not kill the bot."""
        try:
            await self._check_once(time.monotonic())
        except Exception:
            logger.exception("Collision watch pass failed")

    @watch.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_once(self, now: float) -> None:
        if self._tracker is None or self._registry is None:
            return

        live = {s.thread_id for s in self._registry.list_active()}
        if len(live) < 2:
            return

        for collision in find_collisions(self._tracker.snapshot(live, now)):
            if not self._ledger.should_alert(collision, now):
                continue
            self._ledger.record(collision, now)
            logger.info(
                "Collision detected between threads %s and %s on %s",
                collision.threads[0],
                collision.threads[1],
                ", ".join(collision.shared_paths[:5]),
            )
            await self._announce(collision)

    async def _announce(self, collision: Collision) -> None:
        """Post to the lounge (reaches both sessions' next turn) and both threads."""
        if self._lounge_repo is not None:
            try:
                await self._lounge_repo.post(
                    message=build_lounge_notice(collision),
                    label="collision-watch",
                    thread_id=None,
                )
            except Exception:
                logger.exception("Failed to post collision notice to the lounge")
            await self._mirror_to_lounge_channel(build_lounge_notice(collision))

        for thread_id in collision.threads:
            channel = self.bot.get_channel(thread_id)
            if not isinstance(channel, discord.Thread):
                continue
            try:
                await channel.send(build_collision_notice(collision, for_thread=thread_id))
            except Exception:
                logger.exception("Failed to warn thread %s about a collision", thread_id)

    async def _mirror_to_lounge_channel(self, text: str) -> None:
        """Mirror the notice into the human-visible lounge channel, when configured."""
        if self._lounge_channel_id is None:
            return
        channel = self.bot.get_channel(self._lounge_channel_id)
        # discord.py's channel union has no common send(); category and private
        # channels lack it, so probe at runtime and keep the handle untyped.
        send = getattr(channel, "send", None)
        if send is None:
            return
        try:
            await send(f"**[collision-watch]** {text}")
        except Exception:
            logger.exception("Failed to mirror collision notice to the lounge channel")
