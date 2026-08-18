"""DiscordFrontend must satisfy the same contract a Teams frontend will.

The conformance suite is the point: it runs here against the real Discord
adapter and against ``MemoryFrontend`` in ``test_frontend_conformance.py``. A
frontend that passes one and not the other is the bug this exists to catch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_code_core.conformance import check_frontend
from claude_discord.frontend import DiscordFrontend

CHANNEL_ID = 4001
NEXT_THREAD_ID = 5001


class FakeBot:
    """Just enough bot to resolve and create conversations.

    Threads are minted with real ids and remembered, so a conversation created
    through the frontend resolves afterwards exactly as it would against
    Discord — which is precisely what the contract checks.
    """

    def __init__(self) -> None:
        self.channels: dict[int, object] = {}
        self.fetch_calls: list[int] = []
        self._next_thread_id = NEXT_THREAD_ID
        self.channels[CHANNEL_ID] = self._make_channel(CHANNEL_ID)

    def _make_channel(self, channel_id: int) -> MagicMock:
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = channel_id
        message = MagicMock(spec=discord.Message)

        async def create_thread(name: str, **_: object) -> MagicMock:
            thread = MagicMock(spec=discord.Thread)
            thread.id = self._next_thread_id
            thread.name = name
            self._next_thread_id += 1
            self.channels[thread.id] = thread
            return thread

        message.create_thread = AsyncMock(side_effect=create_thread)
        channel.send = AsyncMock(return_value=message)
        return channel

    def get_channel(self, channel_id: int) -> object | None:
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id: int) -> object:
        self.fetch_calls.append(channel_id)
        found = self.channels.get(channel_id)
        if found is None:
            raise discord.NotFound(MagicMock(status=404), "Unknown Channel")
        return found


async def test_discord_frontend_passes_the_shared_contract() -> None:
    async def make() -> DiscordFrontend:
        return DiscordFrontend(FakeBot())  # type: ignore[arg-type]

    report = await check_frontend(make, parent_id=str(CHANNEL_ID))

    assert report.ok, report.summary()


class TestResolve:
    async def test_a_cache_miss_falls_back_to_the_api(self) -> None:
        bot = FakeBot()
        thread = MagicMock(spec=discord.Thread)
        thread.id = 9001
        frontend = DiscordFrontend(bot)  # type: ignore[arg-type]

        # Present to fetch_channel but absent from get_channel: a cold cache.
        bot.channels[9001] = thread
        original_get = bot.get_channel
        bot.get_channel = lambda cid: None if cid == 9001 else original_get(cid)  # type: ignore[assignment]

        surface = await frontend.resolve_surface(9001)

        assert surface is not None
        assert surface.thread_key == 9001
        assert bot.fetch_calls == [9001]

    async def test_a_deleted_thread_is_none_not_an_exception(self) -> None:
        """Scheduler loops run unattended; a deleted thread must not kill one."""
        frontend = DiscordFrontend(FakeBot())  # type: ignore[arg-type]

        assert await frontend.resolve_surface(123456) is None

    async def test_a_channel_kind_that_cannot_hold_a_session_is_none(self) -> None:
        bot = FakeBot()
        forum = MagicMock(spec=discord.ForumChannel)
        forum.id = 7001
        bot.channels[7001] = forum

        assert await DiscordFrontend(bot).resolve_surface(7001) is None  # type: ignore[arg-type]

    async def test_a_text_channel_resolves_for_inline_reply_mode(self) -> None:
        """Mentions are answered in the channel itself, so it is a valid surface."""
        frontend = DiscordFrontend(FakeBot())  # type: ignore[arg-type]

        surface = await frontend.resolve_surface(CHANNEL_ID)

        assert surface is not None
        assert surface.frontend == "discord"


class TestCreate:
    async def test_the_title_names_the_thread(self) -> None:
        frontend = DiscordFrontend(FakeBot())  # type: ignore[arg-type]

        surface = await frontend.create_surface(parent_id=str(CHANNEL_ID), title="nightly build")
        resolved = await frontend.resolve_surface(surface.thread_key)

        assert resolved is not None
        assert resolved.thread_key == surface.thread_key

    async def test_an_overlong_title_is_trimmed_to_discord_limits(self) -> None:
        bot = FakeBot()
        frontend = DiscordFrontend(bot)  # type: ignore[arg-type]

        await frontend.create_surface(parent_id=str(CHANNEL_ID), title="x" * 500)

        created = bot.channels[NEXT_THREAD_ID]
        assert len(created.name) <= 100  # type: ignore[union-attr]

    async def test_an_unknown_channel_is_loud(self) -> None:
        """Unlike a deleted thread, a bad channel id is a configuration error."""
        frontend = DiscordFrontend(FakeBot())  # type: ignore[arg-type]

        with pytest.raises(LookupError):
            await frontend.create_surface(parent_id="999999", title="nope")

    async def test_a_non_numeric_parent_is_loud(self) -> None:
        frontend = DiscordFrontend(FakeBot())  # type: ignore[arg-type]

        with pytest.raises(LookupError):
            await frontend.create_surface(parent_id="general", title="nope")
