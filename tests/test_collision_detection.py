"""Tests for structural collision detection between concurrent sessions.

Covers:
- extract_written_path (which tools count as a write)
- FileActivityTracker windowing and bounding
- find_collisions pairing
- AlertLedger de-duplication
- CollisionWatchCog end-to-end pass (lounge + both threads)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs.collision_watch import CollisionWatchCog
from claude_discord.collision import (
    ACTIVITY_WINDOW_SECONDS,
    ALERT_COOLDOWN_SECONDS,
    MAX_PATHS_PER_THREAD,
    AlertLedger,
    Collision,
    FileActivityTracker,
    build_collision_notice,
    extract_written_path,
    find_collisions,
)
from claude_discord.concurrency import SessionRegistry

A, B, C = 111, 222, 333
SHARED = "/home/ebi/repo/parser.py"

# ---------------------------------------------------------------------------
# extract_written_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_write_tools_yield_their_path(tool: str) -> None:
    assert extract_written_path(tool, {"file_path": SHARED}) == SHARED


def test_notebook_edit_uses_notebook_path() -> None:
    assert extract_written_path("NotebookEdit", {"notebook_path": "/tmp/a.ipynb"}) == "/tmp/a.ipynb"


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "Bash", "WebFetch"])
def test_read_only_tools_are_ignored(tool: str) -> None:
    """Two sessions reading the same file is normal — it must not be a signal."""
    assert extract_written_path(tool, {"file_path": SHARED}) is None


@pytest.mark.parametrize("payload", [{}, {"file_path": ""}, {"file_path": 42}])
def test_missing_or_unusable_paths_yield_none(payload: dict) -> None:
    assert extract_written_path("Edit", payload) is None


# ---------------------------------------------------------------------------
# FileActivityTracker
# ---------------------------------------------------------------------------


def test_recent_paths_respect_the_activity_window() -> None:
    tracker = FileActivityTracker()
    tracker.record(A, SHARED, now=0.0)

    assert tracker.recent_paths(A, now=60.0) == {SHARED}
    assert tracker.recent_paths(A, now=ACTIVITY_WINDOW_SECONDS + 1) == set()


def test_snapshot_omits_threads_without_recent_writes() -> None:
    tracker = FileActivityTracker()
    tracker.record(A, SHARED, now=0.0)

    assert tracker.snapshot({A, B}, now=10.0) == {A: {SHARED}}


def test_forget_drops_a_threads_history() -> None:
    tracker = FileActivityTracker()
    tracker.record(A, SHARED, now=0.0)
    tracker.forget(A)

    assert tracker.snapshot({A}, now=1.0) == {}


def test_tracker_is_bounded_and_evicts_the_oldest_path() -> None:
    tracker = FileActivityTracker()
    for i in range(MAX_PATHS_PER_THREAD + 10):
        tracker.record(A, f"/tmp/f{i}.py", now=float(i))

    paths = tracker.recent_paths(A, now=float(MAX_PATHS_PER_THREAD))
    assert len(paths) <= MAX_PATHS_PER_THREAD
    assert "/tmp/f0.py" not in paths


# ---------------------------------------------------------------------------
# find_collisions
# ---------------------------------------------------------------------------


def test_shared_path_produces_one_ordered_pair() -> None:
    collisions = find_collisions({B: {SHARED, "/x.py"}, A: {SHARED}})

    assert len(collisions) == 1
    assert collisions[0].threads == (A, B)  # lower id first → stable identity
    assert collisions[0].shared_paths == (SHARED,)
    assert collisions[0].other(A) == B


def test_disjoint_sessions_do_not_collide() -> None:
    assert find_collisions({A: {"/a.py"}, B: {"/b.py"}}) == []


def test_three_way_overlap_reports_every_pair() -> None:
    collisions = find_collisions({A: {SHARED}, B: {SHARED}, C: {SHARED}})

    assert {c.threads for c in collisions} == {(A, B), (A, C), (B, C)}


# ---------------------------------------------------------------------------
# AlertLedger
# ---------------------------------------------------------------------------


def test_ledger_suppresses_repeats_until_the_cooldown_passes() -> None:
    ledger = AlertLedger()
    collision = Collision(threads=(A, B), shared_paths=(SHARED,))

    assert ledger.should_alert(collision, now=0.0) is True
    ledger.record(collision, now=0.0)

    assert ledger.should_alert(collision, now=60.0) is False
    assert ledger.should_alert(collision, now=ALERT_COOLDOWN_SECONDS + 1) is True


def test_notice_names_the_peer_the_files_and_what_to_do() -> None:
    text = build_collision_notice(Collision(threads=(A, B), shared_paths=(SHARED,)), for_thread=A)

    assert str(B) in text
    assert SHARED in text
    assert "/api/threads" in text and "/api/claims" in text


# ---------------------------------------------------------------------------
# CollisionWatchCog
# ---------------------------------------------------------------------------


def _make_bot(threads: dict[int, MagicMock]) -> MagicMock:
    bot = MagicMock()
    bot.file_activity = FileActivityTracker()
    bot.session_registry = SessionRegistry()
    bot.get_channel.side_effect = lambda cid: threads.get(cid)
    return bot


def _make_thread(thread_id: int) -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    thread.send = AsyncMock()
    return thread


def _make_cog(bot: MagicMock) -> CollisionWatchCog:
    lounge_repo = MagicMock()
    lounge_repo.post = AsyncMock()
    cog = CollisionWatchCog(bot, lounge_repo=lounge_repo)
    cog.watch.cancel()  # drive _check_once by hand instead of on a timer
    return cog


async def test_watch_warns_both_threads_and_the_lounge() -> None:
    threads = {A: _make_thread(A), B: _make_thread(B)}
    bot = _make_bot(threads)
    bot.session_registry.register(A, "task a", "/home/ebi")
    bot.session_registry.register(B, "task b", "/home/ebi")
    bot.file_activity.record(A, SHARED, now=0.0)
    bot.file_activity.record(B, SHARED, now=1.0)
    cog = _make_cog(bot)

    await cog._check_once(now=2.0)

    threads[A].send.assert_awaited_once()
    threads[B].send.assert_awaited_once()
    assert str(B) in threads[A].send.call_args.args[0]
    assert str(A) in threads[B].send.call_args.args[0]
    cog._lounge_repo.post.assert_awaited_once()


async def test_repeat_pass_does_not_warn_twice() -> None:
    threads = {A: _make_thread(A), B: _make_thread(B)}
    bot = _make_bot(threads)
    bot.session_registry.register(A, "task a", None)
    bot.session_registry.register(B, "task b", None)
    bot.file_activity.record(A, SHARED, now=0.0)
    bot.file_activity.record(B, SHARED, now=0.0)
    cog = _make_cog(bot)

    await cog._check_once(now=1.0)
    await cog._check_once(now=61.0)

    assert threads[A].send.await_count == 1


async def test_idle_peer_is_not_a_collision() -> None:
    """A finished session's edits must not keep flagging a live one."""
    threads = {A: _make_thread(A), B: _make_thread(B)}
    bot = _make_bot(threads)
    bot.session_registry.register(A, "task a", None)  # B is no longer running
    bot.file_activity.record(A, SHARED, now=0.0)
    bot.file_activity.record(B, SHARED, now=0.0)
    cog = _make_cog(bot)

    await cog._check_once(now=1.0)

    threads[A].send.assert_not_awaited()
    cog._lounge_repo.post.assert_not_awaited()


async def test_thread_send_failure_does_not_stop_the_other_warning() -> None:
    threads = {A: _make_thread(A), B: _make_thread(B)}
    threads[A].send.side_effect = RuntimeError("Discord is having a day")
    bot = _make_bot(threads)
    bot.session_registry.register(A, "task a", None)
    bot.session_registry.register(B, "task b", None)
    bot.file_activity.record(A, SHARED, now=0.0)
    bot.file_activity.record(B, SHARED, now=0.0)
    cog = _make_cog(bot)

    await cog._check_once(now=1.0)

    threads[B].send.assert_awaited_once()


# ---------------------------------------------------------------------------
# EventProcessor integration — the hook that feeds the tracker
# ---------------------------------------------------------------------------


def _tool_event(tool_name: str, tool_input: dict):
    from claude_discord.claude.types import MessageType, StreamEvent, ToolCategory, ToolUseEvent

    return StreamEvent(
        message_type=MessageType.ASSISTANT,
        tool_use=ToolUseEvent(
            tool_id="t1",
            tool_name=tool_name,
            tool_input=tool_input,
            category=ToolCategory.EDIT,
        ),
    )


def _processor(tracker: FileActivityTracker, thread_id: int = A):
    from claude_discord.cogs.event_processor import EventProcessor
    from claude_discord.cogs.run_config import RunConfig

    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    thread.send = AsyncMock()
    return EventProcessor(
        RunConfig(
            thread=thread,
            runner=MagicMock(),
            prompt="test prompt",
            file_activity=tracker,
            chat_only=True,  # skip embed posting; we only care about the recording
        )
    )


async def test_event_processor_records_written_paths() -> None:
    tracker = FileActivityTracker()
    processor = _processor(tracker)

    await processor.process(_tool_event("Edit", {"file_path": SHARED}))

    assert tracker.recent_paths(A, now=0.0) == {SHARED}


async def test_event_processor_ignores_reads() -> None:
    tracker = FileActivityTracker()
    processor = _processor(tracker)

    await processor.process(_tool_event("Read", {"file_path": SHARED}))

    assert tracker.recent_paths(A, now=0.0) == set()


async def test_event_processor_without_tracker_is_a_noop() -> None:
    """Consumers that never wire a tracker must not crash on tool use."""
    from claude_discord.cogs.event_processor import EventProcessor
    from claude_discord.cogs.run_config import RunConfig

    thread = MagicMock(spec=discord.Thread)
    thread.id = A
    thread.send = AsyncMock()
    processor = EventProcessor(
        RunConfig(thread=thread, runner=MagicMock(), prompt="p", chat_only=True)
    )

    await processor.process(_tool_event("Write", {"file_path": SHARED}))
