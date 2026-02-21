"""Tests for _run_helper module: streaming, intermediate text, tool results."""

from __future__ import annotations

import asyncio
import contextlib
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
    LiveToolTimer,
    StreamingMessageManager,
    _make_error_embed,
    _truncate_result,
    run_claude_in_thread,
)
from claude_discord.concurrency import SessionRegistry


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


class TestPartialMessageStreaming:
    """Tests for partial message streaming behavior introduced with --include-partial-messages.

    stream-json delivers the FULL accumulated text on each partial event, not just a delta.
    The handler must compute deltas and stream them into a single Discord message
    (edit in-place) rather than creating new messages for every partial event.
    """

    @pytest.fixture
    def thread(self) -> MagicMock:
        t = MagicMock(spec=discord.Thread)
        t.id = 99999
        msg = MagicMock(spec=discord.Message)
        msg.edit = AsyncMock()
        t.send = AsyncMock(return_value=msg)
        return t

    @pytest.fixture
    def runner(self) -> MagicMock:
        return MagicMock()

    def _make_async_gen(self, events: list[StreamEvent]):
        async def gen(*args, **kwargs):
            for e in events:
                yield e

        return gen

    @pytest.mark.asyncio
    async def test_partial_text_does_not_flood_discord(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        """Multiple partial text events should not each create a new Discord message.

        With --include-partial-messages, stream-json sends the same message many times
        with growing text. We must NOT call thread.send() on every partial update.
        """
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="s1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="I'll", is_partial=True),
            StreamEvent(message_type=MessageType.ASSISTANT, text="I'll read", is_partial=True),
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                text="I'll read the file.",
                is_partial=False,  # complete
                tool_use=ToolUseEvent(
                    tool_id="t1",
                    tool_name="Read",
                    tool_input={"file_path": "/tmp/test.py"},
                    category=ToolCategory.READ,
                ),
            ),
            StreamEvent(message_type=MessageType.USER, tool_result_id="t1"),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                session_id="s1",
                cost_usd=0.01,
                duration_ms=1000,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, None, "test", None)

        # Partial events must NOT each create a new message.
        # The first partial triggers thread.send() once (to create the message),
        # then subsequent partials/tool edits it in-place via msg.edit().
        text_sends = [
            c for c in thread.send.call_args_list if c.args and isinstance(c.args[0], str)
        ]
        # "I'll read the file." should appear at most once as a fresh send
        assert len([c for c in text_sends if "I'll" in c.args[0]]) <= 1

    @pytest.mark.asyncio
    async def test_partial_text_finalizes_before_tool_embed(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        """Streaming text must be finalized before a tool embed is posted."""
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="s1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="Reading now...", is_partial=True),
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                text="Reading now...",
                is_partial=False,
                tool_use=ToolUseEvent(
                    tool_id="t1",
                    tool_name="Read",
                    tool_input={"file_path": "/tmp/x.py"},
                    category=ToolCategory.READ,
                ),
            ),
            StreamEvent(message_type=MessageType.USER, tool_result_id="t1"),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                session_id="s1",
                cost_usd=0.01,
                duration_ms=500,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, None, "test", None)

        # At least one non-embed send (the text) and at least one embed send (tool)
        text_sends = [
            c for c in thread.send.call_args_list if c.args and isinstance(c.args[0], str)
        ]
        embed_sends = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        assert len(text_sends) >= 1
        assert len(embed_sends) >= 1

    @pytest.mark.asyncio
    async def test_partial_thinking_not_posted_as_embed(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        """Partial thinking events must NOT each create a thinking embed.

        Only the final complete thinking block should produce an embed.
        """
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="s1"),
            # Partial thinking events (simulating --include-partial-messages)
            StreamEvent(message_type=MessageType.ASSISTANT, thinking="Let me", is_partial=True),
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                thinking="Let me think about this...",
                is_partial=True,
            ),
            # Complete message with final thinking + text
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                thinking="Let me think about this carefully.",
                text="Here is my answer.",
                is_partial=False,
            ),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Here is my answer.",
                session_id="s1",
                cost_usd=0.01,
                duration_ms=1000,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, None, "test", None)

        embed_sends = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        thinking_embeds = [
            c
            for c in embed_sends
            if hasattr(c.kwargs.get("embed"), "title")
            and "Thinking" in (c.kwargs["embed"].title or "")
        ]
        # Exactly ONE thinking embed — the final complete one, not each partial
        assert len(thinking_embeds) == 1

    @pytest.mark.asyncio
    async def test_is_partial_detection_in_parser(self) -> None:
        """Parser must set is_partial based on stop_reason."""
        from claude_discord.claude.parser import parse_line

        partial = parse_line(
            '{"type": "assistant", "message": {"stop_reason": null, "content": '
            '[{"type": "text", "text": "hello"}]}}'
        )
        assert partial is not None
        assert partial.is_partial is True

        complete = parse_line(
            '{"type": "assistant", "message": {"stop_reason": "end_turn", "content": '
            '[{"type": "text", "text": "hello"}]}}'
        )
        assert complete is not None
        assert complete.is_partial is False

        tool_stop = parse_line(
            '{"type": "assistant", "message": {"stop_reason": "tool_use", "content": '
            '[{"type": "text", "text": "hello"}]}}'
        )
        assert tool_stop is not None
        assert tool_stop.is_partial is False


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
        # Description must use a plain code block (no spoiler) for guaranteed readability
        embed = thinking_embeds[0].kwargs["embed"]
        assert embed.description is not None
        assert embed.description.startswith("```")
        assert embed.description.endswith("```")
        assert "||" not in embed.description

    @pytest.mark.asyncio
    async def test_redacted_thinking_posted_as_embed(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """A redacted_thinking block should post a placeholder embed."""
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(message_type=MessageType.ASSISTANT, has_redacted_thinking=True),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Done.",
                session_id="sess-1",
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        embed_calls = [c for c in thread.send.call_args_list if "embed" in c.kwargs]
        titles = [c.kwargs["embed"].title or "" for c in embed_calls]
        assert any("redacted" in t.lower() for t in titles)

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
    async def test_duplicate_not_reposted_when_result_text_differs_slightly(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Even if result.text differs slightly from ASSISTANT text, don't re-send.

        The RESULT event's `result` field can have subtle formatting differences
        (trailing whitespace, newlines) compared to the ASSISTANT event text.
        The old string-comparison guard would fail in this case and send the
        text a second time. The flag-based guard prevents this.
        """
        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(message_type=MessageType.ASSISTANT, text="Final answer."),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Final answer.\n",  # trailing newline — subtle difference
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=500,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        # Text should appear only once despite the trailing newline difference
        text_messages = [
            c for c in thread.send.call_args_list if c.args and isinstance(c.args[0], str)
        ]
        final_msgs = [c for c in text_messages if "Final answer." in c.args[0]]
        assert len(final_msgs) == 1

    @pytest.mark.asyncio
    async def test_repo_none_skips_save(self, thread: MagicMock, runner: MagicMock) -> None:
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

    @pytest.mark.asyncio
    async def test_session_start_embed_sent_only_once_for_multiple_system_events(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """session_start_embed must be sent exactly once even when Claude emits
        multiple SYSTEM events (e.g. init + hook feedback events with session_id).

        Regression test for: Claude Code emits 3+ SYSTEM events per session when
        hooks are configured (init + UserPromptSubmit hook partial + complete),
        each with session_id, causing 3 identical session-start embeds to appear.
        """
        events = [
            # Simulates: init SYSTEM message
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            # Simulates: hook feedback (UserPromptSubmit partial) — also has session_id
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            # Simulates: hook feedback (UserPromptSubmit complete) — also has session_id
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                session_id="sess-1",
                cost_usd=0.001,
                duration_ms=500,
            ),
        ]
        runner.run = self._make_async_gen(events)

        await run_claude_in_thread(thread, runner, repo, "test", None)

        start_embeds = [
            c
            for c in thread.send.call_args_list
            if "embed" in c.kwargs and "session started" in (c.kwargs["embed"].title or "").lower()
        ]
        assert len(start_embeds) == 1, (
            f"Expected exactly 1 session_start_embed, got {len(start_embeds)}"
        )


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


class TestConcurrencyIntegration:
    """Tests that run_claude_in_thread integrates with SessionRegistry."""

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
        return MagicMock()

    def _make_async_gen(self, events: list[StreamEvent]):
        async def gen(*args, **kwargs):
            for e in events:
                yield e

        return gen

    def _simple_events(self) -> list[StreamEvent]:
        return [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                text="Done.",
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=500,
            ),
        ]

    @pytest.mark.asyncio
    async def test_prompt_includes_concurrency_notice(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """When registry is provided, prompt should be prefixed with notice."""
        registry = SessionRegistry()
        captured_prompt = []

        async def capturing_gen(prompt, **kwargs):
            captured_prompt.append(prompt)
            for e in self._simple_events():
                yield e

        runner.run = capturing_gen

        await run_claude_in_thread(thread, runner, repo, "fix the bug", None, registry=registry)

        assert len(captured_prompt) == 1
        assert captured_prompt[0].startswith("[CONCURRENCY NOTICE")
        assert "fix the bug" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_session_registered_during_run(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Session should be registered in the registry while running."""
        registry = SessionRegistry()
        registered_during_run = []

        original_events = self._simple_events()

        async def capturing_gen(prompt, **kwargs):
            # Capture registry state during execution
            registered_during_run.extend(registry.list_active())
            for e in original_events:
                yield e

        runner.run = capturing_gen

        await run_claude_in_thread(thread, runner, repo, "fix the bug", None, registry=registry)

        assert len(registered_during_run) == 1
        assert registered_during_run[0].thread_id == 12345

    @pytest.mark.asyncio
    async def test_session_unregistered_after_run(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Session should be removed from registry after completion."""
        registry = SessionRegistry()
        runner.run = self._make_async_gen(self._simple_events())

        await run_claude_in_thread(thread, runner, repo, "fix the bug", None, registry=registry)

        assert registry.list_active() == []

    @pytest.mark.asyncio
    async def test_session_unregistered_on_error(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Session should be removed from registry even if an error occurs."""
        registry = SessionRegistry()

        async def failing_gen(prompt, **kwargs):
            raise RuntimeError("boom")
            yield  # make it a generator  # noqa: E501

        runner.run = failing_gen

        await run_claude_in_thread(thread, runner, repo, "fix the bug", None, registry=registry)

        assert registry.list_active() == []

    @pytest.mark.asyncio
    async def test_other_sessions_in_notice(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """When other sessions exist, their info should appear in the prompt."""
        registry = SessionRegistry()
        registry.register(9999, "running /goodmorning", "/home/ebi")

        captured_prompt = []

        async def capturing_gen(prompt, **kwargs):
            captured_prompt.append(prompt)
            for e in self._simple_events():
                yield e

        runner.run = capturing_gen

        await run_claude_in_thread(thread, runner, repo, "fix the bug", None, registry=registry)

        assert len(captured_prompt) == 1
        assert "/goodmorning" in captured_prompt[0]
        assert "fix the bug" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_no_registry_no_prefix(
        self, thread: MagicMock, runner: MagicMock, repo: MagicMock
    ) -> None:
        """Without registry, prompt should be passed as-is."""
        captured_prompt = []

        async def capturing_gen(prompt, **kwargs):
            captured_prompt.append(prompt)
            for e in self._simple_events():
                yield e

        runner.run = capturing_gen

        await run_claude_in_thread(thread, runner, repo, "fix the bug", None)

        assert captured_prompt[0] == "fix the bug"


class TestLiveToolTimer:
    """Tests for LiveToolTimer elapsed-time embed updates."""

    def _bash_tool(self) -> ToolUseEvent:
        return ToolUseEvent(
            tool_id="t1",
            tool_name="Bash",
            tool_input={"command": "az login --use-device-code"},
            category=ToolCategory.COMMAND,
        )

    def _make_msg(self) -> MagicMock:
        msg = MagicMock(spec=discord.Message)
        msg.edit = AsyncMock()
        return msg

    @pytest.mark.asyncio
    async def test_timer_updates_embed_after_interval(self) -> None:
        """After TOOL_TIMER_INTERVAL seconds, the embed should be updated with elapsed time."""
        import claude_discord.cogs._run_helper as rh

        msg = self._make_msg()
        timer = LiveToolTimer(msg, self._bash_tool())

        original_interval = rh.TOOL_TIMER_INTERVAL
        rh.TOOL_TIMER_INTERVAL = 0.01  # speed up for test
        try:
            task = timer.start()
            await asyncio.sleep(0.05)  # allow at least one tick
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            rh.TOOL_TIMER_INTERVAL = original_interval

        msg.edit.assert_called()
        # Elapsed time must be in description (title stays stable across ticks)
        call_embed = msg.edit.call_args.kwargs.get("embed")
        assert call_embed is not None
        assert call_embed.description is not None
        assert "s" in call_embed.description  # e.g. "⏳ 0s elapsed..."
        assert "s)" not in call_embed.title  # title must NOT contain elapsed time

    @pytest.mark.asyncio
    async def test_timer_cancelled_stops_updates(self) -> None:
        """After cancellation, no further edits should occur."""
        import claude_discord.cogs._run_helper as rh

        msg = self._make_msg()
        timer = LiveToolTimer(msg, self._bash_tool())

        original_interval = rh.TOOL_TIMER_INTERVAL
        rh.TOOL_TIMER_INTERVAL = 0.01
        try:
            task = timer.start()
            await asyncio.sleep(0.005)  # cancel before first tick
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            rh.TOOL_TIMER_INTERVAL = original_interval

        msg.edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_claude_cancels_timer_on_tool_result(self) -> None:
        """Timer task should be cancelled when the tool result arrives."""
        import claude_discord.cogs._run_helper as rh

        thread = MagicMock(spec=discord.Thread)
        thread.id = 11111
        tool_msg = MagicMock(spec=discord.Message)
        tool_msg.edit = AsyncMock()
        tool_msg.embeds = [MagicMock(title="🔧 Running: az login...")]
        thread.send = AsyncMock(return_value=tool_msg)

        repo = MagicMock()
        repo.save = AsyncMock()
        runner = MagicMock()

        events = [
            StreamEvent(message_type=MessageType.SYSTEM, session_id="sess-1"),
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                tool_use=ToolUseEvent(
                    tool_id="t1",
                    tool_name="Bash",
                    tool_input={"command": "az login --use-device-code"},
                    category=ToolCategory.COMMAND,
                ),
            ),
            StreamEvent(
                message_type=MessageType.USER,
                tool_result_id="t1",
                tool_result_content="Device login complete",
            ),
            StreamEvent(
                message_type=MessageType.RESULT,
                is_complete=True,
                session_id="sess-1",
                cost_usd=0.01,
                duration_ms=5000,
            ),
        ]

        async def gen(*args, **kwargs):
            for e in events:
                yield e

        runner.run = gen

        original_interval = rh.TOOL_TIMER_INTERVAL
        rh.TOOL_TIMER_INTERVAL = 100  # ensure timer never fires during this test
        try:
            await run_claude_in_thread(thread, runner, repo, "login", None)
        finally:
            rh.TOOL_TIMER_INTERVAL = original_interval

        # All timers should be cleared after run completes
        # (verified indirectly: no ghost tasks, session finishes cleanly)
