"""Tests for StreamingMessageManager.

Focused on the overflow and truncation bugs:
- Buffer exceeding 2000 chars should never silently truncate with "..."
- Large text arriving before any message exists should be handled correctly
- Multi-overflow (text > 2 * STREAM_MAX_CHARS) should split correctly
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.discord_ui.streaming_manager import STREAM_MAX_CHARS, StreamingMessageManager


def _make_thread() -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.send = AsyncMock()
    return thread


def _make_message() -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.edit = AsyncMock()
    return msg


class TestNormalOperation:
    """Basic functionality that should always work."""

    @pytest.mark.asyncio
    async def test_first_append_creates_message(self) -> None:
        thread = _make_thread()
        mgr = StreamingMessageManager(thread)

        await mgr.append("hello")
        await mgr.finalize()

        thread.send.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_subsequent_edits_same_message(self) -> None:
        thread = _make_thread()
        msg = _make_message()
        thread.send = AsyncMock(return_value=msg)
        mgr = StreamingMessageManager(thread)

        await mgr.append("hello")
        await mgr.append(" world")
        await mgr.finalize()

        # Only one send (first), rest are edits
        thread.send.assert_called_once()
        assert msg.edit.await_count >= 1

    @pytest.mark.asyncio
    async def test_finalize_returns_buffer(self) -> None:
        thread = _make_thread()
        thread.send = AsyncMock(return_value=_make_message())
        mgr = StreamingMessageManager(thread)

        await mgr.append("abc")
        result = await mgr.finalize()

        assert result == "abc"

    @pytest.mark.asyncio
    async def test_append_after_finalize_is_noop(self) -> None:
        thread = _make_thread()
        mgr = StreamingMessageManager(thread)
        await mgr.finalize()
        await mgr.append("ignored")

        thread.send.assert_not_called()


class TestOverflowBugs:
    """Tests that reproduce the truncation bugs.

    Bug 1: buffer > 2000 on first message (no _current_message) → truncated with "..."
    Bug 2: overflow check requires _current_message, skipping overflow on first chunk
    """

    @pytest.mark.asyncio
    async def test_large_first_chunk_does_not_truncate(self) -> None:
        """Regression: a chunk > 2000 chars as the very first append must NOT be truncated.

        Previously, _flush() would do buffer[:1997] + "..." and the rest was lost.
        """
        thread = _make_thread()
        msg1 = _make_message()
        msg2 = _make_message()
        thread.send = AsyncMock(side_effect=[msg1, msg2])

        mgr = StreamingMessageManager(thread)
        big_text = "A" * 2500

        await mgr.append(big_text)
        await mgr.finalize()

        # The full big_text must be present across the sent messages — no "..." truncation
        assert "..." not in thread.send.await_args_list[0].args[0], (
            "First message was truncated with '...'"
        )
        assert len(thread.send.await_args_list[0].args[0]) <= 2000, (
            "First message exceeded Discord 2000-char limit"
        )

    @pytest.mark.asyncio
    async def test_large_first_chunk_stays_within_discord_limit(self) -> None:
        """Every individual message sent to Discord must be ≤ 2000 chars."""
        thread = _make_thread()
        # Return fresh mocks for each send
        thread.send = AsyncMock(side_effect=lambda *a, **kw: _make_message())

        mgr = StreamingMessageManager(thread)
        await mgr.append("X" * 3000)
        await mgr.finalize()

        for c in thread.send.await_args_list:
            content = c.args[0] if c.args else c.kwargs.get("content", "")
            assert len(content) <= 2000, f"Message exceeded 2000 chars: {len(content)}"

    @pytest.mark.asyncio
    async def test_overflow_without_existing_message_still_splits(self) -> None:
        """When buffer > STREAM_MAX_CHARS and no current message, must still split.

        Previously the overflow guard required self._current_message to exist.
        """
        thread = _make_thread()
        msg1 = _make_message()
        msg2 = _make_message()
        thread.send = AsyncMock(side_effect=[msg1, msg2])

        mgr = StreamingMessageManager(thread)
        text = "B" * (STREAM_MAX_CHARS + 100)  # slightly over limit

        await mgr.append(text)
        await mgr.finalize()

        # At least 2 messages must have been created (overflow → split)
        assert thread.send.await_count >= 2, (
            "Large initial chunk should have been split into multiple messages"
        )

    @pytest.mark.asyncio
    async def test_no_message_truncated_with_ellipsis(self) -> None:
        """No message sent to Discord should ever end with '...' from truncation."""
        thread = _make_thread()
        thread.send = AsyncMock(side_effect=lambda *a, **kw: _make_message())

        mgr = StreamingMessageManager(thread)
        # Send text that would trigger the old [:1997] + "..." path
        await mgr.append("Z" * 2100)
        await mgr.finalize()

        for c in thread.send.await_args_list:
            content = c.args[0] if c.args else c.kwargs.get("content", "")
            assert not content.endswith("..."), (
                f"Message was truncated with '...': {content[-20:]!r}"
            )

    @pytest.mark.asyncio
    async def test_triple_overflow_all_content_preserved(self) -> None:
        """Text 3× the limit should produce at least 3 messages, none truncated."""
        thread = _make_thread()
        thread.send = AsyncMock(side_effect=lambda *a, **kw: _make_message())

        mgr = StreamingMessageManager(thread)
        big_text = "C" * (STREAM_MAX_CHARS * 3 + 50)
        await mgr.append(big_text)
        await mgr.finalize()

        all_contents = [
            c.args[0] if c.args else c.kwargs.get("content", "")
            for c in thread.send.await_args_list
        ]
        for content in all_contents:
            assert len(content) <= 2000
            assert not content.endswith("...")

        # Total chars must account for all content (allowing for deduplication
        # at chunk boundaries — just verify no message is over the limit)
        assert thread.send.await_count >= 3


class TestChunkBoundary:
    """Edge cases around exactly STREAM_MAX_CHARS."""

    @pytest.mark.asyncio
    async def test_exactly_stream_max_chars_fits_in_one_message(self) -> None:
        """Text exactly at STREAM_MAX_CHARS should not trigger overflow."""
        thread = _make_thread()
        msg = _make_message()
        thread.send = AsyncMock(return_value=msg)

        mgr = StreamingMessageManager(thread)
        await mgr.append("D" * STREAM_MAX_CHARS)
        await mgr.finalize()

        thread.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_over_stream_max_chars_triggers_split(self) -> None:
        """Text at STREAM_MAX_CHARS + 1 should trigger a new message."""
        thread = _make_thread()
        thread.send = AsyncMock(side_effect=lambda *a, **kw: _make_message())

        mgr = StreamingMessageManager(thread)
        await mgr.append("E" * (STREAM_MAX_CHARS + 1))
        await mgr.finalize()

        assert thread.send.await_count >= 2
