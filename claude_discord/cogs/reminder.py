"""ReminderCog — ``/remind``, ``/reminders``, and the notification send loop.

Two jobs, one Cog, because they are the two halves of the same feature.

**Delivery.** A 30-second loop drains ``scheduled_notifications`` and posts them.
Without it, ``POST /api/schedule`` is a black hole: rows accumulate and nothing
ever sends them.  The loop lives in the framework so every deployment gets it —
a consumer must not have to write a Cog to make a documented endpoint work.

**Scheduling.** ``/remind`` picks the cheapest mechanism that can express what
was asked:

* no ``check`` → a notification row.  One Discord message, no agent, no cost.
* with ``check`` → a scheduled task, so a real session verifies the condition
  first and stays silent when the thing is already done.

That split is the whole point.  An unconditional reminder does not need
judgement, and a conditional one cannot work without it.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..reminders import (
    build_conditional_prompt,
    build_plain_reminder_text,
    extract_reminder_what,
    parse_until,
    parse_when,
    repeat_interval_seconds,
)

if TYPE_CHECKING:
    from ..database.notification_repo import NotificationRepository
    from ..database.task_repo import TaskRepository

logger = logging.getLogger(__name__)

DRAIN_INTERVAL_SECONDS = 30
_REMINDER_COLOR = 0x00BFFF
_MAX_LISTED = 20
# Discord stores notification times as naive local strings; keep the format in
# one place so the drain query and the writer cannot drift apart.
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _reminder_embed(message: str, title: str | None = None) -> discord.Embed:
    return discord.Embed(
        title=title or "⏰ Reminder",
        description=message,
        color=_REMINDER_COLOR,
        timestamp=datetime.now().astimezone(),
    )


class ReminderCog(commands.Cog):
    """Scheduled reminders: plain notifications and condition-checked ones.

    Args:
        bot: The Discord bot instance.
        notification_repo: Store for plain (unconditional) reminders.
        task_repo: Scheduler store, used for conditional reminders. When None
            (scheduler disabled) ``/remind`` still handles plain reminders and
            says plainly that conditional ones are unavailable.
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        notification_repo: NotificationRepository,
        task_repo: TaskRepository | None = None,
    ) -> None:
        self.bot = bot
        self.notification_repo = notification_repo
        self.task_repo = task_repo

    async def cog_load(self) -> None:
        self._drain_loop.start()
        logger.info("ReminderCog loaded — notification drain loop started")

    def cog_unload(self) -> None:
        self._drain_loop.cancel()

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    @tasks.loop(seconds=DRAIN_INTERVAL_SECONDS)
    async def _drain_loop(self) -> None:
        await self.drain_notifications()

    @_drain_loop.before_loop
    async def _before_drain_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def drain_notifications(self) -> None:
        """Send every notification whose time has come.

        One failure never blocks the rest of the queue, and a failed row is
        marked failed rather than retried forever — a reminder that is hours
        late is noise, not a reminder.
        """
        now = datetime.now().strftime(_TIME_FORMAT)
        for notification in await self.notification_repo.get_pending(before=now):
            notification_id = notification["id"]
            try:
                target = await self._resolve_target(notification.get("channel_id"))
                if target is None:
                    await self.notification_repo.mark_failed(notification_id, "No channel")
                    continue
                embed = _reminder_embed(notification["message"], notification.get("title"))
                if notification.get("color"):
                    embed.color = notification["color"]
                await target.send(embed=embed)
                await self.notification_repo.mark_sent(notification_id)
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the queue
                logger.warning("Reminder %d could not be sent: %s", notification_id, exc)
                await self.notification_repo.mark_failed(notification_id, str(exc))

    async def _resolve_target(self, channel_id: int | None) -> Any:
        """Resolve a channel or thread to post into, falling back to the default."""
        resolved_id = channel_id or getattr(self.bot, "default_channel_id", None)
        if not resolved_id:
            return None
        channel = self.bot.get_channel(int(resolved_id))
        if channel is None:
            channel = await self.bot.fetch_channel(int(resolved_id))
        return channel

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="remind",
        description="Remind me later — optionally only if it is still not done",
    )
    @app_commands.describe(
        when="21:30, 2h, or 2026-08-08T09:00",
        what="What to remind you about",
        check="Optional: how to tell it is already done (stays silent if so)",
        every="Optional repeat: daily, hourly, weekly, 6h, 30m",
        until="Optional expiry: 2026-08-08 or 2d — required when repeating",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        when: str,
        what: str,
        check: str | None = None,
        every: str | None = None,
        until: str | None = None,
    ) -> None:
        """Schedule a reminder, conditional if *check* is given."""
        try:
            fire_at = parse_when(when)
            expires_at = parse_until(until)
            interval = repeat_interval_seconds(every)
        except ValueError as exc:
            await self._reject(interaction, str(exc))
            return

        # A repeat that can neither be satisfied nor expire never stops.
        if every is not None and check is None and expires_at is None:
            await self._reject(
                interaction,
                "A repeating reminder needs `until` (an expiry) or `check` "
                "(a condition that ends it) — otherwise it nags forever.",
            )
            return

        if check is None:
            await self._schedule_plain(interaction, fire_at, what, every, expires_at)
        else:
            await self._schedule_conditional(
                interaction, fire_at, what, check, interval, every, expires_at
            )

    async def _schedule_plain(
        self,
        interaction: discord.Interaction,
        fire_at: datetime,
        what: str,
        every: str | None,
        expires_at: datetime | None,
    ) -> None:
        """Store an unconditional reminder as a notification (no agent run)."""
        if every is not None:
            await self._reject(
                interaction,
                "Repeating plain reminders are not supported — add `check` so the "
                "reminder can tell when it is done, or schedule single reminders.",
            )
            return
        try:
            message = build_plain_reminder_text(what)
        except ValueError as exc:
            await self._reject(interaction, str(exc))
            return

        await self.notification_repo.create(
            message=message,
            scheduled_at=fire_at.strftime(_TIME_FORMAT),
            source="slash_command",
            channel_id=interaction.channel_id,
        )
        await interaction.response.send_message(
            embed=self._confirmation(fire_at, what, conditional=False, every=None, until=expires_at)
        )

    async def _schedule_conditional(
        self,
        interaction: discord.Interaction,
        fire_at: datetime,
        what: str,
        check: str,
        interval: int,
        every: str | None,
        expires_at: datetime | None,
    ) -> None:
        """Register a scheduled task that verifies before it speaks."""
        if self.task_repo is None:
            await self._reject(
                interaction,
                "Conditional reminders need the scheduler, which is disabled in "
                "this deployment. A plain reminder (without `check`) still works.",
            )
            return

        channel = interaction.channel
        parent_id = getattr(channel, "parent_id", None)
        in_thread = parent_id is not None
        thread_id = interaction.channel_id if in_thread else None
        channel_id = parent_id if in_thread else interaction.channel_id
        if channel_id is None:
            await self._reject(interaction, "Cannot schedule a reminder outside a channel.")
            return

        # Unique per invocation: the same reminder may legitimately be set twice.
        name = f"remind-{interaction.channel_id}-{int(time.time() * 1000)}"
        try:
            prompt = build_conditional_prompt(what=what, check=check, task_name=name)
        except ValueError as exc:
            await self._reject(interaction, str(exc))
            return

        await self.task_repo.create(
            name=name,
            prompt=prompt,
            interval_seconds=interval,
            channel_id=int(channel_id),
            thread_id=thread_id,
            one_shot=every is None,
            run_at=fire_at.timestamp(),
            until=expires_at.timestamp() if expires_at else None,
        )
        await interaction.response.send_message(
            embed=self._confirmation(
                fire_at, what, conditional=True, every=every, until=expires_at, check=check
            )
        )

    @app_commands.command(name="reminders", description="List pending reminders")
    async def reminders(self, interaction: discord.Interaction) -> None:
        """Show every reminder that has not fired yet."""
        lines: list[str] = []
        for notification in (await self.notification_repo.get_pending())[:_MAX_LISTED]:
            lines.append(
                f"⏰ `{notification['scheduled_at']}` — {notification['message']}"
                f" (id `{notification['id']}`)"
            )
        if self.task_repo is not None:
            for task in await self.task_repo.get_all():
                if not task["enabled"] or not task["name"].startswith("remind-"):
                    continue
                fires = datetime.fromtimestamp(task["next_run_at"]).strftime("%m/%d %H:%M")
                subject = extract_reminder_what(task["prompt"]) or task["name"]
                lines.append(f"🔍 `{fires}` — {subject} (`{task['name']}`)")

        if not lines:
            await interaction.response.send_message("No pending reminders.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⏰ Pending reminders",
                description="\n".join(lines),
                color=_REMINDER_COLOR,
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _reject(interaction: discord.Interaction, message: str) -> None:
        """Tell the user why nothing was scheduled. Never fail silently."""
        await interaction.response.send_message(message, ephemeral=True)

    @staticmethod
    def _confirmation(
        fire_at: datetime,
        what: str,
        *,
        conditional: bool,
        every: str | None,
        until: datetime | None,
        check: str | None = None,
    ) -> discord.Embed:
        detail = [f"**{fire_at.strftime('%m/%d %H:%M')}** — {what}"]
        if conditional:
            detail.append(f"Only if not done yet: {check}")
        if every:
            detail.append(f"Repeats: {every}")
        if until:
            detail.append(f"Stops after: {until.strftime('%m/%d %H:%M')}")
        return discord.Embed(
            title="✅ Reminder set",
            description="\n".join(detail),
            color=_REMINDER_COLOR,
        )
