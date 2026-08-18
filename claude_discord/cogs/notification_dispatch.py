"""NotificationDispatchCog — delivers the notifications the REST API accepts.

``POST /api/schedule`` stores a row and answers ``{"status": "scheduled"}``.
Something has to read that row back at its due time and post it, and that
something belongs here rather than in a consumer's custom Cog: the endpoint is
part of ccdb, so its delivery has to ship with ccdb (CLAUDE.md, Zero-Config).

The Cog is constructed with the *repository object* the API server writes
through — never with a path of its own.  A scheduled notification that is
accepted but never delivered is indistinguishable from a delivered one at the
API surface (it is listed by ``GET /api/scheduled`` either way), so the only
safe design is one where a second database cannot come into existence.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from ..database.notification_repo import NotificationRepository

logger = logging.getLogger(__name__)

# Matches SchedulerCog's cadence: the worst-case lateness a user can observe.
DISPATCH_INTERVAL_SECONDS = 30

DEFAULT_COLOR = 0x00BFFF

# How late a notification may be and still be worth sending.  A restart or a
# maintenance window costs minutes and those reminders should still arrive; a
# notification whose day has passed has lost its context, and firing a backlog
# of them the moment delivery is restored is its own kind of failure.
DEFAULT_STALE_AFTER_SECONDS = 24 * 60 * 60


class NotificationDispatchCog(commands.Cog):
    """Post scheduled notifications once they come due.

    Args:
        bot: The Discord bot instance.
        repo: The same NotificationRepository the API server writes through.
        default_channel_id: Where to post rows stored without a channel.
        stale_after_seconds: Lateness past which a notification is dropped
            rather than delivered.
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        repo: NotificationRepository,
        default_channel_id: int | None = None,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.default_channel_id = default_channel_id
        self.stale_after_seconds = stale_after_seconds

    async def cog_load(self) -> None:
        self._dispatch_loop.start()
        logger.info("NotificationDispatchCog loaded — dispatch loop started")

    def cog_unload(self) -> None:
        self._dispatch_loop.cancel()
        logger.info("NotificationDispatchCog unloaded — dispatch loop stopped")

    @tasks.loop(seconds=DISPATCH_INTERVAL_SECONDS)
    async def _dispatch_loop(self) -> None:
        await self.dispatch_due()

    @_dispatch_loop.before_loop
    async def _before_dispatch_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def dispatch_due(self) -> None:
        """Send every pending notification whose time has passed.

        ``scheduled_at`` is stored as a local-time ISO string without an
        offset, so the comparison is made in the same form the writer used.
        """
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        due = await self.repo.get_pending(before=now)
        if not due:
            return

        logger.info("NotificationDispatchCog: %d notification(s) due", len(due))
        for notification in due:
            # One bad row (deleted channel, revoked access) must not hold back
            # the queue behind it, so each is marked and stepped over.
            await self._deliver(notification)

    async def _deliver(self, notification: dict[str, Any]) -> None:
        notification_id: int = notification["id"]
        try:
            lateness = self._lateness_seconds(notification["scheduled_at"])
            if lateness is not None and lateness > self.stale_after_seconds:
                logger.warning(
                    "Notification %d is stale (%.0f h late) — not delivering",
                    notification_id,
                    lateness / 3600,
                )
                await self.repo.mark_failed(
                    notification_id,
                    f"stale: {lateness / 3600:.0f}h past its scheduled time",
                )
                return

            channel = await self._resolve_channel(notification.get("channel_id"))
            if channel is None:
                logger.warning("No channel for notification %d", notification_id)
                await self.repo.mark_failed(notification_id, "No channel ID")
                return

            await channel.send(embed=self._build_embed(notification))
            await self.repo.mark_sent(notification_id)
            logger.info("Notification sent: id=%d", notification_id)
        except Exception as exc:
            logger.exception("Failed to send notification %d", notification_id)
            await self.repo.mark_failed(notification_id, str(exc))

    @staticmethod
    def _lateness_seconds(scheduled_at: str) -> float | None:
        """Seconds between the due time and now, or None if it cannot be read.

        Returning None means "do not judge": the due-time comparison is done on
        strings, so a malformed value can reach here, and being unable to
        measure a row's age is not evidence that it is too old to send.
        """
        try:
            return (datetime.now() - datetime.fromisoformat(scheduled_at)).total_seconds()
        except (ValueError, TypeError):
            logger.warning(
                "Unparseable scheduled_at %r — skipping the staleness check", scheduled_at
            )
            return None

    async def _resolve_channel(self, channel_id: object) -> Any:
        target = channel_id or self.default_channel_id
        if not target:
            return None
        channel: Any = self.bot.get_channel(int(target))  # type: ignore[arg-type]
        if channel is None:
            channel = await self.bot.fetch_channel(int(target))  # type: ignore[arg-type]
        return channel

    @staticmethod
    def _build_embed(notification: dict[str, Any]) -> discord.Embed:
        """Render the row the API stored, matching the REST API's embed."""
        return discord.Embed(
            title=notification.get("title") or "⏰ Reminder",
            description=notification["message"],
            color=notification.get("color") or DEFAULT_COLOR,
            timestamp=datetime.now(),
        )
