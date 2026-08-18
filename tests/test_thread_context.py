"""Tests for discord_ui/thread_context.py — recent-history transcript builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from claude_discord.discord_ui.thread_context import build_recent_transcript


def _msg(
    content: str,
    *,
    author: str = "alice",
    bot: bool = False,
    msg_id: int = 1,
    minutes_ago: int = 10,
) -> MagicMock:
    m = MagicMock()
    m.id = msg_id
    m.content = content
    m.author = MagicMock()
    m.author.bot = bot
    m.author.display_name = author
    m.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return m


def _thread(messages: list[MagicMock]) -> MagicMock:
    thread = MagicMock()

    def history(**kwargs: object) -> object:
        async def gen():  # noqa: ANN202 - test helper
            for m in messages:
                yield m

        return gen()

    thread.history = history
    thread.id = 999
    return thread


class TestBuildThreadTranscript:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_thread(self) -> None:
        assert await build_recent_transcript(_thread([])) is None

    @pytest.mark.asyncio
    async def test_formats_messages_oldest_first_with_author(self) -> None:
        out = await build_recent_transcript(
            _thread(
                [
                    _msg("first", author="alice", msg_id=1, minutes_ago=30),
                    _msg("second", author="bob", msg_id=2, minutes_ago=20),
                ]
            )
        )
        assert out is not None
        assert out.index("alice: first") < out.index("bob: second")

    @pytest.mark.asyncio
    async def test_excludes_the_triggering_message(self) -> None:
        """The message that summoned Claude is the prompt — not context."""
        out = await build_recent_transcript(
            _thread([_msg("old", msg_id=1), _msg("@bot help", msg_id=42)]),
            exclude_message_id=42,
        )
        assert out is not None
        assert "@bot help" not in out
        assert "old" in out

    @pytest.mark.asyncio
    async def test_skips_messages_without_text(self) -> None:
        """Embed-only status messages carry no content worth spending tokens on."""
        out = await build_recent_transcript(_thread([_msg("real"), _msg("", msg_id=2)]))
        assert out is not None
        assert out.count("\n[") == 0 or "real" in out
        assert len([ln for ln in out.splitlines() if ln.startswith("[")]) == 1

    @pytest.mark.asyncio
    async def test_bot_messages_are_kept_and_labelled(self) -> None:
        """Claude's own past replies are part of the conversation others read."""
        out = await build_recent_transcript(
            _thread([_msg("bot said this", author="ClaudeCode", bot=True)])
        )
        assert out is not None
        assert "bot said this" in out

    @pytest.mark.asyncio
    async def test_long_messages_are_truncated(self) -> None:
        out = await build_recent_transcript(_thread([_msg("x" * 5000)]), max_message_chars=100)
        assert out is not None
        assert "x" * 101 not in out

    @pytest.mark.asyncio
    async def test_oldest_messages_dropped_when_over_budget(self) -> None:
        """The budget keeps the newest turns — those are the ones being replied to."""
        msgs = [_msg(f"message-{i}", msg_id=i, minutes_ago=100 - i) for i in range(1, 21)]
        out = await build_recent_transcript(_thread(msgs), max_chars=300)
        assert out is not None
        assert "message-20" in out
        assert "message-1 " not in out
        assert len(out) < 700  # header + trimmed body

    @pytest.mark.asyncio
    async def test_history_is_bounded_by_the_cutoff(self) -> None:
        """Only the last `days` days are requested from Discord."""
        captured: dict[str, object] = {}
        thread = MagicMock()

        def history(**kwargs: object) -> object:
            captured.update(kwargs)

            async def gen():  # noqa: ANN202 - test helper
                for m in [_msg("hi")]:
                    yield m

            return gen()

        thread.history = history
        thread.id = 1
        await build_recent_transcript(thread, days=7)

        after = captured["after"]
        assert isinstance(after, datetime)
        delta = datetime.now(UTC) - after
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)
        assert captured["oldest_first"] is True

    @pytest.mark.asyncio
    async def test_returns_none_when_history_fails(self) -> None:
        """A missing-permission thread must degrade to "no context", never raise."""
        thread = MagicMock()
        thread.id = 1

        def history(**kwargs: object) -> object:
            raise RuntimeError("Missing Access")

        thread.history = history
        assert await build_recent_transcript(thread) is None
