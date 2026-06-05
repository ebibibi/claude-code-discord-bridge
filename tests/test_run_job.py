"""Tests for the engine-neutral one-shot collector (run_job.collect_oneshot).

collect_oneshot drives any SessionBackend.run(prompt) async generator to
completion and returns the final text — without knowing whether the backend
is Claude, Codex, or anything else.
"""

from __future__ import annotations

import pytest

from claude_discord.claude.types import MessageType, StreamEvent
from claude_discord.run_job import RunError, collect_oneshot

from .conftest import make_async_gen


class _FakeBackend:
    """Minimal SessionBackend stand-in exposing only run()."""

    def __init__(self, events: list[StreamEvent]) -> None:
        self.run = make_async_gen(events)


class TestCollectOneshot:
    async def test_returns_result_text(self) -> None:
        backend = _FakeBackend(
            [
                StreamEvent(message_type=MessageType.SYSTEM, session_id="s"),
                StreamEvent(message_type=MessageType.ASSISTANT, text="partial "),
                StreamEvent(message_type=MessageType.RESULT, is_complete=True, text="Final answer"),
            ]
        )
        out = await collect_oneshot(backend, "hi")
        assert out == "Final answer"

    async def test_falls_back_to_assistant_text_when_no_result_text(self) -> None:
        backend = _FakeBackend(
            [
                StreamEvent(message_type=MessageType.ASSISTANT, text="hello "),
                StreamEvent(message_type=MessageType.ASSISTANT, text="world"),
                StreamEvent(message_type=MessageType.RESULT, is_complete=True, text=None),
            ]
        )
        out = await collect_oneshot(backend, "hi")
        assert out == "hello world"

    async def test_uses_raw_result_field(self) -> None:
        backend = _FakeBackend(
            [
                StreamEvent(
                    message_type=MessageType.RESULT,
                    is_complete=True,
                    text=None,
                    raw={"result": "from raw"},
                ),
            ]
        )
        out = await collect_oneshot(backend, "hi")
        assert out == "from raw"

    async def test_raises_on_error_event(self) -> None:
        backend = _FakeBackend(
            [
                StreamEvent(message_type=MessageType.RESULT, error="rate limited"),
            ]
        )
        with pytest.raises(RunError, match="rate limited"):
            await collect_oneshot(backend, "hi")
