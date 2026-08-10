"""Coalescing updates so a long session does not run out of budget.

Teams allows 1,800 operations per hour per conversation. A session that shows
a live status changes it far more often than that, so the question is never
"may I update" but "which update do I actually spend a slot on". The answer
this pacer gives is: the newest one, and never more than one per interval.

The tests drive a fake clock and a fake sleep, because a pacer tested with
real time either sleeps for real or proves nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from claude_teams.pacer import UpdatePacer

INTERVAL = 2.0


class FakeClock:
    """A clock the test moves, with a sleep that yields rather than waits."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds
        await asyncio.sleep(0)


def pacer(clock: FakeClock, interval: float = INTERVAL) -> UpdatePacer:
    return UpdatePacer(interval, now=clock.now, sleep=clock.sleep)


class TestFirstUpdate:
    async def test_the_first_update_is_not_delayed(self) -> None:
        # Nobody is waiting on a budget yet, and an artificial 2s before the
        # first sign of life is exactly what makes a bot feel dead.
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "first"))
        assert done == ["first"]
        assert clock.slept == []


class TestCoalescing:
    async def test_updates_inside_the_interval_collapse_to_the_newest(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "a"))
        await p.submit(lambda: _record(done, "b"))
        await p.submit(lambda: _record(done, "c"))
        assert done == ["a"], "only the first should have gone out immediately"

        await p.drain()
        # Not ["a", "b", "c"]: b was superseded before it ever cost a slot.
        assert done == ["a", "c"]
        await p.close()

    async def test_a_submit_after_the_interval_goes_straight_out(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "a"))
        clock.t += INTERVAL + 0.1
        await p.submit(lambda: _record(done, "b"))
        assert done == ["a", "b"]
        assert clock.slept == [], "no wait was needed, so none should have happened"
        await p.close()


class TestFlush:
    async def test_flush_sends_the_pending_update_now(self) -> None:
        # The last state of a session is worth a slot even if it lands early:
        # a card frozen on "running" after the session ended is a lie that
        # stays on screen.
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "a"))
        await p.submit(lambda: _record(done, "final"))
        await p.flush()
        assert done == ["a", "final"]
        await p.close()

    async def test_flush_with_nothing_pending_does_nothing(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "a"))
        await p.flush()
        await p.flush()
        assert done == ["a"]
        await p.close()

    async def test_flush_does_not_replay_an_update_the_timer_already_sent(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "a"))
        await p.submit(lambda: _record(done, "b"))
        await p.drain()
        await p.flush()
        assert done == ["a", "b"]
        await p.close()


class TestFailures:
    async def test_a_failing_update_does_not_wedge_the_pacer(self) -> None:
        # An edit can fail for reasons that have nothing to do with the next
        # one — a transient 429, a message someone deleted. If the failure
        # left the pacer holding a slot, the conversation would go silent for
        # the rest of the session.
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        async def boom() -> None:
            raise RuntimeError("edit failed")

        await p.submit(boom)
        clock.t += INTERVAL + 0.1
        await p.submit(lambda: _record(done, "after"))
        assert done == ["after"]
        await p.close()

    async def test_a_failing_deferred_update_does_not_wedge_the_pacer(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        async def boom() -> None:
            raise RuntimeError("edit failed")

        await p.submit(lambda: _record(done, "a"))
        await p.submit(boom)
        await p.drain()

        clock.t += INTERVAL + 0.1
        await p.submit(lambda: _record(done, "after"))
        assert done == ["a", "after"]
        await p.close()


class TestClose:
    async def test_close_drops_a_pending_update(self) -> None:
        # Close means the conversation is over. Letting a queued edit land
        # afterwards would repaint a card the session has already finished
        # with.
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "a"))
        await p.submit(lambda: _record(done, "never"))
        await p.close()
        await asyncio.sleep(0)
        assert done == ["a"]

    async def test_submitting_after_close_is_refused_quietly(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.close()
        await p.submit(lambda: _record(done, "late"))
        assert done == []


class TestConstruction:
    def test_a_non_positive_interval_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_interval"):
            UpdatePacer(0.0)


async def _record(sink: list[str], value: str) -> None:
    sink.append(value)


class TestTargets:
    async def test_a_second_target_is_not_displaced_by_the_first(self) -> None:
        # The card and the streaming reply are different messages. Coalescing
        # them together would have a card repaint silently swallow a pending
        # stream edit, and the answer would stop growing for no visible reason.
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "first"))
        await p.submit(lambda: _record(done, "stream"), key="stream")
        await p.submit(lambda: _record(done, "card"), key="card")
        assert done == ["first"]

        await p.drain()
        assert done == ["first", "stream"], "the longest-waiting target goes first"
        await p.drain()
        assert done == ["first", "stream", "card"], "the other target must still get its turn"
        await p.close()

    async def test_repeat_submits_to_one_target_do_not_starve_another(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "first"))
        await p.submit(lambda: _record(done, "card-1"), key="card")
        await p.submit(lambda: _record(done, "stream-1"), key="stream")
        await p.submit(lambda: _record(done, "card-2"), key="card")

        await p.drain()
        await p.drain()
        # card-1 was superseded by card-2 and never cost a slot; the stream
        # kept its place in the queue rather than being pushed back by it.
        assert done == ["first", "card-2", "stream-1"]
        await p.close()

    async def test_flush_sends_every_target(self) -> None:
        clock = FakeClock()
        p = pacer(clock)
        done: list[str] = []

        await p.submit(lambda: _record(done, "first"))
        await p.submit(lambda: _record(done, "stream"), key="stream")
        await p.submit(lambda: _record(done, "card"), key="card")
        await p.flush()
        assert sorted(done) == ["card", "first", "stream"]
        await p.close()
