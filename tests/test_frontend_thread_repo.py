"""The ledger that turns a ThreadKey back into a place to post.

``derive_thread_key`` is one-way. A session row stores only the key, so without
this table a Teams deployment could look up a session and still have no idea
which conversation it belonged to. That is the whole reason the table exists,
and it is what these tests pin.
"""

from __future__ import annotations

import pytest

from claude_discord.database.frontend_thread_repo import FrontendThreadRepository
from claude_discord.database.models import init_db


@pytest.fixture
async def repo(tmp_path) -> FrontendThreadRepository:
    db = str(tmp_path / "sessions.db")
    await init_db(db)
    return FrontendThreadRepository(db)


class TestRegister:
    async def test_a_registered_conversation_resolves_back_to_its_address(
        self, repo: FrontendThreadRepository
    ) -> None:
        key = await repo.register("teams", "19:abc@thread.tacv2", parent_external_id="team-1")

        record = await repo.resolve(key)

        assert record is not None
        assert record.frontend == "teams"
        assert record.external_id == "19:abc@thread.tacv2"
        assert record.parent_external_id == "team-1"

    async def test_registering_twice_returns_the_same_key(
        self, repo: FrontendThreadRepository
    ) -> None:
        """Registration runs on every resolve, so it has to be idempotent."""
        first = await repo.register("teams", "19:abc@thread.tacv2")
        second = await repo.register("teams", "19:abc@thread.tacv2")

        assert first == second

    async def test_a_discord_thread_keeps_its_snowflake(
        self, repo: FrontendThreadRepository
    ) -> None:
        assert await repo.register("discord", "1535820929958027334") == 1535820929958027334

    async def test_two_conversations_never_share_a_key(
        self, repo: FrontendThreadRepository
    ) -> None:
        a = await repo.register("teams", "19:aaa@thread.tacv2")
        b = await repo.register("teams", "19:bbb@thread.tacv2")

        assert a != b

    async def test_the_same_id_on_two_frontends_stays_separate(
        self, repo: FrontendThreadRepository
    ) -> None:
        a = await repo.register("teams", "conversation-1")
        b = await repo.register("slack", "conversation-1")

        assert a != b
        assert (await repo.resolve(a)).frontend == "teams"  # type: ignore[union-attr]
        assert (await repo.resolve(b)).frontend == "slack"  # type: ignore[union-attr]

    async def test_a_later_parent_is_recorded_without_changing_the_key(
        self, repo: FrontendThreadRepository
    ) -> None:
        """The key is the identity; the parent is where to reopen it."""
        key = await repo.register("teams", "19:abc@thread.tacv2")

        again = await repo.register("teams", "19:abc@thread.tacv2", parent_external_id="team-9")

        assert again == key
        assert (await repo.resolve(key)).parent_external_id == "team-9"  # type: ignore[union-attr]


class TestLookup:
    async def test_an_unknown_key_resolves_to_none(self, repo: FrontendThreadRepository) -> None:
        assert await repo.resolve(999_999) is None

    async def test_a_key_can_be_found_from_the_frontend_address(
        self, repo: FrontendThreadRepository
    ) -> None:
        key = await repo.register("teams", "19:abc@thread.tacv2")

        assert await repo.key_for("teams", "19:abc@thread.tacv2") == key
        assert await repo.key_for("teams", "19:missing@thread.tacv2") is None


class TestBackfill:
    async def test_existing_discord_sessions_are_adopted(self, tmp_path) -> None:
        """An upgrade must not leave every existing thread unaddressable."""
        import aiosqlite

        db = str(tmp_path / "sessions.db")
        await init_db(db)
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT INTO sessions (thread_id, session_id) VALUES (?, ?)", (12345, "sess-a")
            )
            await conn.commit()

        repo = FrontendThreadRepository(db)
        adopted = await repo.backfill_discord()

        assert adopted == 1
        record = await repo.resolve(12345)
        assert record is not None
        assert record.frontend == "discord"
        assert record.external_id == "12345"

    async def test_backfill_is_idempotent(self, tmp_path) -> None:
        import aiosqlite

        db = str(tmp_path / "sessions.db")
        await init_db(db)
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT INTO sessions (thread_id, session_id) VALUES (?, ?)", (12345, "sess-a")
            )
            await conn.commit()

        repo = FrontendThreadRepository(db)
        await repo.backfill_discord()
        second = await repo.backfill_discord()

        assert second == 0
