"""Tests for ReminderCog — /remind, /reminders, and the notification drain loop.

The drain loop is the part worth guarding: before it existed in the framework,
``POST /api/schedule`` happily accepted notifications that nothing ever sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.cogs.reminder import ReminderCog
from claude_discord.database.notification_repo import NotificationRepository
from claude_discord.database.task_repo import TaskRepository


@pytest.fixture
async def notif_repo(tmp_path) -> NotificationRepository:
    r = NotificationRepository(str(tmp_path / "notifications.db"))
    await r.init_db()
    return r


@pytest.fixture
async def task_repo(tmp_path) -> TaskRepository:
    r = TaskRepository(str(tmp_path / "tasks.db"))
    await r.init_db()
    return r


@pytest.fixture
def channel() -> MagicMock:
    ch = MagicMock()
    ch.send = AsyncMock()
    return ch


@pytest.fixture
def bot(channel: MagicMock) -> MagicMock:
    b = MagicMock()
    b.get_channel = MagicMock(return_value=channel)
    b.fetch_channel = AsyncMock(return_value=channel)
    b.default_channel_id = 999
    return b


@pytest.fixture
def cog(bot: MagicMock, notif_repo, task_repo) -> ReminderCog:
    return ReminderCog(bot, notification_repo=notif_repo, task_repo=task_repo)


def _interaction(*, in_thread: bool = True) -> MagicMock:
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.channel_id = 555
    interaction.channel = MagicMock()
    interaction.channel.id = 555
    interaction.channel.parent_id = 111 if in_thread else None
    return interaction


def _past(**delta: float) -> str:
    return (datetime.now() - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S")


class TestDrainLoop:
    async def test_sends_due_notification_and_marks_it_sent(
        self, cog: ReminderCog, notif_repo: NotificationRepository, channel: MagicMock
    ) -> None:
        await notif_repo.create(message="買い物", scheduled_at=_past(minutes=1), channel_id=555)

        await cog.drain_notifications()

        channel.send.assert_awaited_once()
        assert await notif_repo.get_pending() == []

    async def test_future_notification_is_left_alone(
        self, cog: ReminderCog, notif_repo: NotificationRepository, channel: MagicMock
    ) -> None:
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        await notif_repo.create(message="later", scheduled_at=future, channel_id=555)

        await cog.drain_notifications()

        channel.send.assert_not_awaited()
        assert len(await notif_repo.get_pending()) == 1

    async def test_falls_back_to_the_default_channel(
        self, cog: ReminderCog, notif_repo: NotificationRepository, bot: MagicMock
    ) -> None:
        await notif_repo.create(message="no channel", scheduled_at=_past(minutes=1))

        await cog.drain_notifications()

        bot.get_channel.assert_called_with(999)

    async def test_send_failure_marks_failed_and_does_not_retry_forever(
        self, cog: ReminderCog, notif_repo: NotificationRepository, channel: MagicMock
    ) -> None:
        channel.send.side_effect = RuntimeError("discord is down")
        await notif_repo.create(message="doomed", scheduled_at=_past(minutes=1), channel_id=555)

        await cog.drain_notifications()

        assert await notif_repo.get_pending() == []

    async def test_one_bad_notification_does_not_block_the_next(
        self, cog: ReminderCog, notif_repo: NotificationRepository, channel: MagicMock
    ) -> None:
        channel.send.side_effect = [RuntimeError("boom"), None]
        await notif_repo.create(message="first", scheduled_at=_past(minutes=2), channel_id=555)
        await notif_repo.create(message="second", scheduled_at=_past(minutes=1), channel_id=555)

        await cog.drain_notifications()

        assert channel.send.await_count == 2


class TestRemindPlain:
    async def test_schedules_a_notification(
        self, cog: ReminderCog, notif_repo: NotificationRepository
    ) -> None:
        interaction = _interaction()

        await cog.remind.callback(cog, interaction, when="2h", what="ゴミ出し")

        pending = await notif_repo.get_pending()
        assert len(pending) == 1
        assert "ゴミ出し" in pending[0]["message"]
        assert pending[0]["channel_id"] == 555

    async def test_does_not_spawn_a_session(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        """A plain reminder is a message, not an agent run — no task row."""
        await cog.remind.callback(cog, _interaction(), when="2h", what="ゴミ出し")

        assert await task_repo.get_all() == []

    async def test_confirms_to_the_user(self, cog: ReminderCog) -> None:
        interaction = _interaction()
        await cog.remind.callback(cog, interaction, when="21:30", what="x")
        interaction.response.send_message.assert_awaited_once()

    async def test_bad_time_is_rejected_without_scheduling(
        self, cog: ReminderCog, notif_repo: NotificationRepository
    ) -> None:
        interaction = _interaction()

        await cog.remind.callback(cog, interaction, when="tonight", what="x")

        assert await notif_repo.get_pending() == []
        kwargs = interaction.response.send_message.await_args.kwargs
        assert kwargs.get("ephemeral") is True

    async def test_blank_message_is_rejected(
        self, cog: ReminderCog, notif_repo: NotificationRepository
    ) -> None:
        await cog.remind.callback(cog, _interaction(), when="2h", what="   ")
        assert await notif_repo.get_pending() == []


class TestRemindConditional:
    async def test_registers_a_scheduled_task_with_the_condition(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        await cog.remind.callback(
            cog,
            _interaction(),
            when="21:30",
            what="IDR のアンケートを出す",
            check="Gmail の in:sent to:idr.co に返信があるか",
        )

        tasks = await task_repo.get_all()
        assert len(tasks) == 1
        assert "in:sent to:idr.co" in tasks[0]["prompt"]
        assert "IDR のアンケートを出す" in tasks[0]["prompt"]

    async def test_posts_into_the_current_thread(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        await cog.remind.callback(
            cog, _interaction(in_thread=True), when="21:30", what="x", check="y"
        )

        task = (await task_repo.get_all())[0]
        assert task["thread_id"] == 555
        assert task["channel_id"] == 111

    async def test_outside_a_thread_it_uses_the_channel(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        await cog.remind.callback(
            cog, _interaction(in_thread=False), when="21:30", what="x", check="y"
        )

        task = (await task_repo.get_all())[0]
        assert task["thread_id"] is None
        assert task["channel_id"] == 555

    async def test_one_shot_unless_it_repeats(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        await cog.remind.callback(cog, _interaction(), when="21:30", what="x", check="y")
        assert (await task_repo.get_all())[0]["one_shot"] is True

    async def test_repeating_reminder_is_not_one_shot(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        await cog.remind.callback(
            cog, _interaction(), when="21:30", what="x", check="y", every="daily"
        )
        task = (await task_repo.get_all())[0]
        assert task["one_shot"] is False
        assert task["interval_seconds"] == 86400

    async def test_until_is_stored(self, cog: ReminderCog, task_repo: TaskRepository) -> None:
        tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
        await cog.remind.callback(
            cog, _interaction(), when="21:30", what="x", check="y", every="daily", until=tomorrow
        )
        assert (await task_repo.get_all())[0]["until"] is not None

    async def test_repeating_without_until_is_rejected(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        """A repeat with no expiry and no condition to satisfy nags forever."""
        interaction = _interaction()

        await cog.remind.callback(cog, interaction, when="21:30", what="x", every="daily")

        assert await task_repo.get_all() == []
        assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True

    async def test_task_name_is_unique_per_invocation(
        self, cog: ReminderCog, task_repo: TaskRepository
    ) -> None:
        await cog.remind.callback(cog, _interaction(), when="21:30", what="x", check="y")
        await cog.remind.callback(cog, _interaction(), when="22:30", what="x", check="y")

        names = {t["name"] for t in await task_repo.get_all()}
        assert len(names) == 2

    async def test_scheduler_disabled_is_reported_not_ignored(
        self, bot: MagicMock, notif_repo: NotificationRepository
    ) -> None:
        cog = ReminderCog(bot, notification_repo=notif_repo, task_repo=None)
        interaction = _interaction()

        await cog.remind.callback(cog, interaction, when="21:30", what="x", check="y")

        assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True


class TestRemindersList:
    async def test_lists_both_kinds(
        self, cog: ReminderCog, notif_repo: NotificationRepository
    ) -> None:
        await cog.remind.callback(cog, _interaction(), when="2h", what="plain one")
        await cog.remind.callback(
            cog, _interaction(), when="21:30", what="conditional one", check="cond"
        )

        interaction = _interaction()
        await cog.reminders.callback(cog, interaction)

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        assert "plain one" in embed.description
        assert "conditional one" in embed.description

    async def test_says_so_when_empty(self, cog: ReminderCog) -> None:
        interaction = _interaction()
        await cog.reminders.callback(cog, interaction)
        assert interaction.response.send_message.await_args is not None
