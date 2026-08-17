"""Tests for NotificationDispatchCog — the loop that actually delivers.

Regression context: ``POST /api/schedule`` wrote to the deployment's
``notifications.db`` while the only send loop in the tree (an example custom
Cog) read a hardcoded ``data/bot.db``.  Every scheduled notification was
accepted, listed and cancellable — and never delivered.  The tests below pin
the properties that make that class of bug impossible:

* the dispatcher reads through the *same repository object* the API writes to
  (``test_dispatcher_shares_the_api_repository_object``), so the two can never
  drift onto different files again,
* a deployment with an API server always gets a dispatcher, with no wiring
  from the consumer (``tests/test_setup.py``), and
* restoring the loop does not replay a backlog of notifications whose moment
  has passed (``TestStale``).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.cogs.notification_dispatch import NotificationDispatchCog
from claude_discord.database.notification_repo import NotificationRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def repo() -> AsyncIterator[NotificationRepository]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = NotificationRepository(path)
    await repo.init_db()
    yield repo
    os.unlink(path)


def _ago(**delta: float) -> str:
    """A due time in the past, in the local-time format the writer uses."""
    return (datetime.now() - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S")


def _ahead(**delta: float) -> str:
    return (datetime.now() + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S")


def _bot_with_channel(channel: MagicMock) -> MagicMock:
    bot = MagicMock()
    bot.get_channel.return_value = channel
    bot.fetch_channel = AsyncMock(return_value=channel)
    return bot


def _messageable() -> MagicMock:
    channel = MagicMock()
    channel.send = AsyncMock()
    return channel


class TestDispatch:
    async def test_sends_due_notification_and_marks_sent(
        self, repo: NotificationRepository
    ) -> None:
        await repo.create(message="時間です", scheduled_at=_ago(minutes=1), channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        channel.send.assert_awaited_once()
        assert await repo.get_pending() == []

    async def test_does_not_send_before_scheduled_time(self, repo: NotificationRepository) -> None:
        await repo.create(message="まだ先", scheduled_at=_ahead(hours=1), channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        channel.send.assert_not_awaited()
        assert len(await repo.get_pending()) == 1

    async def test_falls_back_to_default_channel(self, repo: NotificationRepository) -> None:
        await repo.create(message="宛先なし", scheduled_at=_ago(minutes=1))
        channel = _messageable()
        bot = _bot_with_channel(channel)
        cog = NotificationDispatchCog(bot, repo=repo, default_channel_id=777)

        await cog.dispatch_due()

        bot.get_channel.assert_called_once_with(777)
        channel.send.assert_awaited_once()

    async def test_marks_failed_when_no_channel_can_be_resolved(
        self, repo: NotificationRepository
    ) -> None:
        await repo.create(message="宛先不明", scheduled_at=_ago(minutes=1))
        cog = NotificationDispatchCog(MagicMock(), repo=repo, default_channel_id=None)

        await cog.dispatch_due()

        assert await repo.get_pending() == []
        rows = await _all_rows(repo)
        assert rows[0]["status"] == "failed"
        assert rows[0]["error_message"]

    async def test_marks_failed_when_send_raises(self, repo: NotificationRepository) -> None:
        await repo.create(message="送信失敗", scheduled_at=_ago(minutes=1), channel_id=42)
        channel = _messageable()
        channel.send.side_effect = RuntimeError("Missing Access")
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        rows = await _all_rows(repo)
        assert rows[0]["status"] == "failed"
        assert "Missing Access" in rows[0]["error_message"]

    async def test_one_failure_does_not_block_the_rest(self, repo: NotificationRepository) -> None:
        await repo.create(message="1本目", scheduled_at=_ago(minutes=2), channel_id=1)
        await repo.create(message="2本目", scheduled_at=_ago(minutes=1), channel_id=2)
        channel = _messageable()
        channel.send.side_effect = [RuntimeError("boom"), None]
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        statuses = [row["status"] for row in await _all_rows(repo)]
        assert statuses == ["failed", "sent"]


class TestStale:
    """Restoring the loop must not replay a backlog whose moment has passed."""

    async def test_does_not_deliver_a_notification_from_days_ago(
        self, repo: NotificationRepository
    ) -> None:
        await repo.create(message="1ヶ月前の予定", scheduled_at=_ago(days=30), channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        channel.send.assert_not_awaited()
        rows = await _all_rows(repo)
        assert rows[0]["status"] == "failed"
        assert "stale" in rows[0]["error_message"]

    async def test_still_delivers_after_a_short_outage(self, repo: NotificationRepository) -> None:
        """A restart or a brief maintenance window must not drop reminders."""
        await repo.create(message="再起動中に来た", scheduled_at=_ago(minutes=20), channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        channel.send.assert_awaited_once()

    async def test_stale_window_is_configurable(self, repo: NotificationRepository) -> None:
        await repo.create(message="2時間前", scheduled_at=_ago(hours=2), channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(
            _bot_with_channel(channel), repo=repo, stale_after_seconds=3600
        )

        await cog.dispatch_due()

        channel.send.assert_not_awaited()

    async def test_unparseable_due_time_is_delivered_not_dropped(
        self, repo: NotificationRepository
    ) -> None:
        """A row we cannot age must not be silently discarded as stale.

        The due-time comparison is a string one, so a malformed value can still
        sort into the due set; being unable to measure its age is not evidence
        that it is old.
        """
        await repo.create(message="壊れた日時", scheduled_at="2020-13-45T99:99:99", channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        channel.send.assert_awaited_once()


class TestNoDrift:
    """The properties that keep write-side and read-side on one database."""

    async def test_dispatcher_shares_the_api_repository_object(
        self, repo: NotificationRepository
    ) -> None:
        """The Cog must hold the very object the API writes through.

        Comparing paths would still allow two repositories to be constructed
        from two different defaults; sharing the object cannot.
        """
        from claude_discord.ext.api_server import ApiServer

        api = ApiServer(repo=repo, bot=MagicMock(), default_channel_id=1)
        cog = NotificationDispatchCog(MagicMock(), repo=api.repo)

        assert cog.repo is api.repo

    async def test_a_notification_written_by_the_api_is_visible_to_the_dispatcher(
        self, repo: NotificationRepository
    ) -> None:
        """End-to-end on one repo: what /api/schedule stores, dispatch sends."""
        await repo.create(message="APIが書いた", scheduled_at=_ago(minutes=1), channel_id=42)
        channel = _messageable()
        cog = NotificationDispatchCog(_bot_with_channel(channel), repo=repo)

        await cog.dispatch_due()

        sent = channel.send.await_args.kwargs["embed"]
        assert sent.description == "APIが書いた"


async def _all_rows(repo: NotificationRepository) -> list[dict]:
    import aiosqlite

    async with aiosqlite.connect(repo.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM scheduled_notifications ORDER BY id")
        return [dict(row) for row in await cursor.fetchall()]
