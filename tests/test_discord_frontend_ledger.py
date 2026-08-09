"""A conversation Discord hands out must also be findable by key alone.

Discord does not need the ledger to function — its snowflake is already the
key. It is registered anyway, because a deployment that later gains a second
frontend needs one table that answers "where does this key live", and a table
that only knows half the conversations answers it wrongly rather than not at
all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.database.frontend_thread_repo import FrontendThreadRepository
from claude_discord.database.models import init_db
from claude_discord.frontend import DiscordFrontend

CHANNEL_ID = 4001


class FakeBot:
    def __init__(self) -> None:
        self.channels: dict[int, object] = {}
        self._next_thread_id = 5001
        self.channels[CHANNEL_ID] = self._make_channel(CHANNEL_ID)

    def _make_channel(self, channel_id: int) -> MagicMock:
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = channel_id
        message = MagicMock(spec=discord.Message)

        async def create_thread(name: str, **_: object) -> MagicMock:
            thread = MagicMock(spec=discord.Thread)
            thread.id = self._next_thread_id
            thread.name = name
            thread.parent_id = channel_id
            self._next_thread_id += 1
            self.channels[thread.id] = thread
            return thread

        message.create_thread = AsyncMock(side_effect=create_thread)
        channel.send = AsyncMock(return_value=message)
        return channel

    def get_channel(self, channel_id: int) -> object | None:
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id: int) -> object:
        found = self.channels.get(channel_id)
        if found is None:
            raise discord.NotFound(MagicMock(status=404), "Unknown Channel")
        return found


@pytest.fixture
async def ledger(tmp_path) -> FrontendThreadRepository:
    db = str(tmp_path / "sessions.db")
    await init_db(db)
    return FrontendThreadRepository(db)


async def test_a_created_conversation_is_recorded_with_its_parent(
    ledger: FrontendThreadRepository,
) -> None:
    frontend = DiscordFrontend(FakeBot(), ledger=ledger)  # type: ignore[arg-type]

    surface = await frontend.create_surface(parent_id=str(CHANNEL_ID), title="nightly")

    record = await ledger.resolve(surface.thread_key)
    assert record is not None
    assert record.frontend == "discord"
    assert record.external_id == str(surface.thread_key)
    assert record.parent_external_id == str(CHANNEL_ID)


async def test_resolving_adopts_a_conversation_the_ledger_had_not_seen(
    ledger: FrontendThreadRepository,
) -> None:
    """Threads predating the ledger are learned the first time they are used."""
    frontend = DiscordFrontend(FakeBot(), ledger=ledger)  # type: ignore[arg-type]

    await frontend.resolve_surface(CHANNEL_ID)

    assert await ledger.key_for("discord", str(CHANNEL_ID)) == CHANNEL_ID


async def test_a_missing_conversation_is_not_recorded(
    ledger: FrontendThreadRepository,
) -> None:
    """Recording a thread that does not exist would make the ledger lie."""
    frontend = DiscordFrontend(FakeBot(), ledger=ledger)  # type: ignore[arg-type]

    assert await frontend.resolve_surface(999999) is None
    assert await ledger.key_for("discord", "999999") is None


async def test_the_frontend_works_without_a_ledger() -> None:
    """Zero-Config: an older deployment that never wired one keeps working."""
    frontend = DiscordFrontend(FakeBot())  # type: ignore[arg-type]

    surface = await frontend.create_surface(parent_id=str(CHANNEL_ID), title="nightly")

    assert surface.thread_key


async def test_a_ledger_failure_never_breaks_the_conversation(
    ledger: FrontendThreadRepository,
) -> None:
    """The ledger is bookkeeping. A session must not die because a write failed."""
    ledger.register = AsyncMock(side_effect=RuntimeError("disk full"))  # type: ignore[method-assign]
    frontend = DiscordFrontend(FakeBot(), ledger=ledger)  # type: ignore[arg-type]

    surface = await frontend.create_surface(parent_id=str(CHANNEL_ID), title="nightly")

    assert surface.thread_key
