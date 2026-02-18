"""Tests for _run_helper module: streaming, intermediate text, tool results."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.claude.types import (
    MessageType,
    StreamEvent,
    ToolCategory,
    ToolUseEvent,
)
from claude_discord.cogs._run_helper import (
    TOOL_RESULT_MAX_CHARS,
    StreamingMessageManager,
    _make_error_embed,
    _truncate_result,
    run_claude_in_thread,
)
from claude_discord.discord_ui.embeds import timeout_embed


class TestTruncateResult:
    def test_short_content_unchanged(self) -> None:
        assert _truncate_result("hello") == "hello"

    def test_exact_limit_unchanged(self) -> None:
        text = "x" * TOOL_RESULT_MAX_CHARS
        assert _truncate_result(text) == text

    def test_long_content_truncated(self) -> None:
        text = "x" * (TOOL_RESULT_MAX_CHARS + 100)
        result = _truncate_result(text)
        assert result.endswith("... (truncated)")
        assert len(result) < len(text)

    def test_empty_content(self) -> None:
        assert _truncate_result("") == ""


class TestStreamingMessageManager:
    @pytest.fixture
    def thread(self) -> MagicMock:
        t = MagicMock(spec=discord.Thread)
        msg = MagicMock(spec=discord.Message)
        t.send = AsyncMock(return_value=msg)
        msg.edit = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_has_content_initially_false(self, thread: MagicMock) -> None:
        mgr = StreamingMessageManager(thread)
        assert mgr.has_content is False

    @pytest.mark.asyncio
    async def test_append_sets_has_content(self, thread: MagicMock) -> None:
        mgr = StreamingMessageManager(thread)
        await mgr.append("hello")
        assert mgr.has_content is True

    @pytest.mark.asyncio
    async def test_finalize_returns_buffer(self, thread: MagicMock) -> None:
        mgr = StreamingMessageManager(thread)
        mgr._buffer = "test content"
        result = await mgr.finalize()
        assert result == "test content"

    @pytest.mark.asyncio
    async def test_finalize_sends_message(self, thread: MagicMock) -> None:
        mgr = StreamingMessageManager(thread)
        mgr._buffer = "test content"
        await mgr.finalize()
        thread.send.assert_called_once_with("test content")

    @pytest.mark.asyncio
    async def test_append_after_finalize_ignored(self, thread: MagicMock) -> None:
        mgr = StreamingMessageManager(thread)
        mgr._buffer = "first"
        await mgr.finalize()
        await mgr.append("second")
        # Buffer should still be "first" — append after finalize is ignored
        assert mgr._buffer == "first"


class TestRunClaudeInThread:
    """Integration tests for run_claude_in_thread with mocked runner."""

    @pytest.fixture
    def thread(self) -> MagicMock:
        t = MagicMock(spec=discord.Thread)
        t.id = 12345
        t.send = AsyncMock(return_value=MagicMock(spec=discord.Message))
        return t

    @pytest.fixture
    def repo(self) -> MagicMock:
        r = MagicMock()
        r.save = AsyncMock()
        return r

    @pytest.fixture
    def runner(self) -> MagicMock:
        r = MagicMock()
        return r

    def _make_async_gen(self, events: list[StreamEvent]):
        """Create a mock async generator from a list of events."""

        async def gen(*args, **kwargs):
            for e in events:
                yield e

        return gen

    @pytest.mark.asyncio
    async def test_intermediate_text_posted_immediately(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Intermediate assistant text should be posted to thread, not just accumulated."""
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="I'll read the file now."),
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                tool_use=ToolUseEvent(
                    tool_id="t1",
                    tool_name="Read",
                    tool_input={"file_path": "/tmp/test.py"},
                    category=ToolCategory.READ,
                ),
            ),
            StreamEvent(message_type=MessageType.USER, tool_result_id="t1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="Here's what I found."),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Here's what I found.",
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=2000,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        # Check that intermediate text was posted (not just final)
        send_calls = thread.send.call_args_list
        text_messages = [c for c in send_calls if c.args and isinstance(c.args[0], str)]
        assert len(text_messages) >= 2  # "I'll read the file now." + "Here's what I found."
        assert text_messages[0].args[0] == "I'll read the file now."

    @pytest.mark.asyncio
    async def test_tool_result_updates_embed(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Tool result content should update the tool use embed."""
        tool_msg = MagicMock(spec=discord.Message)
        tool_msg.edit = AsyncMock()
        tool_msg.embeds = [MagicMock(title="📖 Reading: /tmp/test.py...")]
        thread.send = AsyncMock(return_value=tool_msg)

        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                tool_use=ToolUseEvent(
                    tool_id="t1",
                    tool_name="Read",
                    tool_input={"file_path": "/tmp/test.py"},
                    category=ToolCategory.READ,
                ),
            ),
            StreamEvent(
                message_type=MessageType.USER,
                tool_result_id="t1",
                tool_result_content="print('hello world')",
            ),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=1000,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        # Tool message should have been edited with result
        tool_msg.edit.assert_called()

    @pytest.mark.asyncio
    async def test_thinking_posted_as_embed(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Extended thinking should be posted as a spoiler embed."""
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(message_type=MessageType.ASSISTANT, thinking="Let me analyze this..."),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Done!",
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=500,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        # Check that thinking embed was sent
        embed_calls = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        thinking_embeds = [
            c
            for c in embed_calls
            if hasattr(c.kwargs.get("embed"), "title")
            and "Thinking" in (c.kwargs["embed"].title or "")
        ]
        assert len(thinking_embeds) == 1

    @pytest.mark.asyncio
    async def test_error_handling(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Errors should be posted as error embeds."""
        events = [
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                error="Something went wrong",
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        embed_calls = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        assert any("Error" in (c.kwargs["embed"].title or "") for c in embed_calls)

    @pytest.mark.asyncio
    async def test_duplicate_final_text_not_reposted(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """If result.text == last posted text, don't post it again."""
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="Final answer."),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Final answer.",
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=500,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        # "Final answer." should appear only once as text
        text_messages = [
            c for c in thread.send.call_args_list if c.args and isinstance(c.args[0], str)
        ]
        final_msgs = [c for c in text_messages if c.args[0] == "Final answer."]
        assert len(final_msgs) == 1

    @pytest.mark.asyncio
    async def test_repo_none_skips_save(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        """When repo is None (automated workflows), session save should be skipped."""
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="Done."),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Done.",
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=500,
            ),
        ]
        runner.run = self._make_async_gen(events)

        # Should not raise even with repo=None
        result = await run_claude_in_thread(thread, runner, None, "test", None)
        assert result == "sess-1"

    @pytest.mark.asyncio
    async def test_timeout_error_uses_timeout_embed(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Timeout errors should use timeout_embed, not the generic error_embed."""
        events = [
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                error="Timed out after 300 seconds",
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        embed_calls = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        assert any("timed out" in (c.kwargs["embed"].title or "").lower() for c in embed_calls)
        # Must NOT be the generic "Error" embed
        assert not any(c.kwargs["embed"].title == "❌ Error" for c in embed_calls)

    @pytest.mark.asyncio
    async def test_non_timeout_error_uses_error_embed(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Non-timeout errors should still use the generic error_embed."""
        events = [
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                error="CLI exited with code 1",
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        embed_calls = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        assert any("Error" in (c.kwargs["embed"].title or "") for c in embed_calls)


class TestMakeErrorEmbed:
    """Unit tests for the _make_error_embed router function."""

    def test_timeout_message_returns_timeout_embed(self) -> None:
        embed = _make_error_embed("Timed out after 300 seconds")
        assert "timed out" in embed.title.lower()

    def test_timeout_message_includes_seconds(self) -> None:
        embed = _make_error_embed("Timed out after 120 seconds")
        assert "120" in embed.description

    def test_generic_error_returns_error_embed(self) -> None:
        embed = _make_error_embed("Something went wrong")
        assert embed.title == "❌ Error"
        assert "Something went wrong" in embed.description

    def test_partial_timeout_text_uses_error_embed(self) -> None:
        # "Timed out" not at start — should NOT match
        embed = _make_error_embed("Process Timed out after 300 seconds")
        assert embed.title == "❌ Error"
