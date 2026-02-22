"""Shared pytest fixtures for claude_discord tests.

These fixtures are automatically available to all test files in this directory.
Class-level fixtures with the same name take precedence (pytest scoping rules).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.claude.types import MessageType, StreamEvent


@pytest.fixture
def thread() -> MagicMock:
    """A MagicMock discord.Thread with send and id set."""
    t = MagicMock(spec=discord.Thread)
    t.id = 12345
    msg = MagicMock(spec=discord.Message)
    msg.edit = AsyncMock()
    t.send = AsyncMock(return_value=msg)
    return t


@pytest.fixture
def runner() -> MagicMock:
    """A MagicMock ClaudeRunner with interrupt() wired up."""
    r = MagicMock()
    r.interrupt = AsyncMock()
    return r


@pytest.fixture
def repo() -> MagicMock:
    """A MagicMock SessionRepository with async save/get."""
    r = MagicMock()
    r.save = AsyncMock()
    r.get = AsyncMock(return_value=None)
    return r


def make_async_gen(events: list[StreamEvent]):
    """Return an async generator factory that yields the given events.

    Usage::

        runner.run = make_async_gen([event1, event2])
        async for e in runner.run("prompt"):
            ...
    """

    async def gen(*args, **kwargs):
        for e in events:
            yield e

    return gen


def simple_events(session_id: str = "sess-1") -> list[StreamEvent]:
    """Return a minimal sequence: SYSTEM + RESULT (no tool use)."""
    return [
        StreamEvent(message_type=MessageType.SYSTEM, session_id=session_id),
        StreamEvent(
            message_type=MessageType.RESULT,
            is_complete=True,
            text="Done.",
            session_id=session_id,
            cost_usd=0.01,
            duration_ms=500,
        ),
    ]
