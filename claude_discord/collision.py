"""Structural collision detection between concurrent sessions.

The AI Lounge only catches overlaps a session bothered to announce.  This
module catches the ones nobody mentioned, from what the sessions actually did:
if two live sessions have written to the same file in the last few minutes,
they are working on the same thing whether or not either of them said so.

Why file paths rather than working directories: on a single-user host every
session tends to start in the same home directory, so ``working_dir`` equality
flags every pair and means nothing.  A shared *edited file* is a signal that is
almost never a coincidence.

Everything here is pure and clock-injected — the bot supplies ``now`` — so the
rules are testable without a running loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Tools that change a file. Read/Grep/Glob are deliberately excluded: two
# sessions reading the same file is normal and would drown the real signal.
WRITE_TOOL_NAMES = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

# How long a write keeps counting as "current work".
ACTIVITY_WINDOW_SECONDS = 15 * 60.0
# Per pair of threads: never re-alert about the same collision this often.
ALERT_COOLDOWN_SECONDS = 30 * 60.0
# Bound on remembered paths per thread, so a long session cannot grow unbounded.
MAX_PATHS_PER_THREAD = 200
# Shared paths listed in a notice; the rest are summarised as a count.
MAX_LISTED_PATHS = 5


def extract_written_path(tool_name: str, tool_input: dict) -> str | None:
    """Return the file path a tool is about to modify, if it modifies one."""
    if tool_name not in WRITE_TOOL_NAMES:
        return None
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str):
        return None
    path = path.strip()
    return path or None


@dataclass
class FileActivityTracker:
    """Remembers which files each thread wrote to, and when.

    In-memory and process-local: after a restart there is no in-flight work to
    compare, and persisting would resurrect stale collisions.
    """

    _writes: dict[int, dict[str, float]] = field(default_factory=dict)

    def record(self, thread_id: int, path: str, now: float) -> None:
        """Note that *thread_id* wrote *path* at *now* (monotonic seconds)."""
        paths = self._writes.setdefault(thread_id, {})
        paths[path] = now
        if len(paths) > MAX_PATHS_PER_THREAD:
            oldest = min(paths, key=lambda p: paths[p])
            del paths[oldest]

    def forget(self, thread_id: int) -> None:
        """Drop a thread's history (its session ended)."""
        self._writes.pop(thread_id, None)

    def recent_paths(self, thread_id: int, now: float) -> set[str]:
        """Paths this thread wrote inside the activity window."""
        paths = self._writes.get(thread_id, {})
        return {p for p, at in paths.items() if now - at <= ACTIVITY_WINDOW_SECONDS}

    def snapshot(self, thread_ids: set[int], now: float) -> dict[int, set[str]]:
        """Recent paths per thread, omitting threads with no recent writes."""
        result = {}
        for thread_id in thread_ids:
            paths = self.recent_paths(thread_id, now)
            if paths:
                result[thread_id] = paths
        return result


@dataclass(frozen=True)
class Collision:
    """Two live threads that recently wrote to the same file(s)."""

    threads: tuple[int, int]
    shared_paths: tuple[str, ...]

    def other(self, thread_id: int) -> int:
        """The counterpart thread in this pair."""
        first, second = self.threads
        return second if thread_id == first else first


def find_collisions(snapshot: dict[int, set[str]]) -> list[Collision]:
    """Return every pair of threads sharing at least one recently written file.

    Pairs are ordered (lower thread id first) so the same collision always has
    the same identity, which is what makes de-duplication possible.
    """
    collisions: list[Collision] = []
    thread_ids = sorted(snapshot)
    for i, first in enumerate(thread_ids):
        for second in thread_ids[i + 1 :]:
            shared = snapshot[first] & snapshot[second]
            if shared:
                collisions.append(
                    Collision(threads=(first, second), shared_paths=tuple(sorted(shared)))
                )
    return collisions


@dataclass
class AlertLedger:
    """Remembers which collisions were already announced.

    Without this, a 60-second watcher would repeat the same warning every minute
    for as long as the overlap lasts — the fastest way to make sessions (and the
    human reading the channel) learn to ignore it.
    """

    _last_alert: dict[tuple[int, int], float] = field(default_factory=dict)

    def should_alert(self, collision: Collision, now: float) -> bool:
        last = self._last_alert.get(collision.threads)
        return last is None or now - last >= ALERT_COOLDOWN_SECONDS

    def record(self, collision: Collision, now: float) -> None:
        self._last_alert[collision.threads] = now


def format_paths(paths: tuple[str, ...]) -> str:
    """Render shared paths for a notice, capping the list length."""
    listed = ", ".join(f"`{p}`" for p in paths[:MAX_LISTED_PATHS])
    remaining = len(paths) - MAX_LISTED_PATHS
    return f"{listed} (+{remaining} more)" if remaining > 0 else listed


def build_collision_notice(collision: Collision, *, for_thread: int) -> str:
    """The warning posted into a colliding thread.

    It names the peer and the evidence, then points at the tools that resolve
    it — a warning with no next step just becomes noise.
    """
    other = collision.other(for_thread)
    return (
        "⚠️ **Possible collision with another session**\n"
        f"Thread `{other}` has written to the same file(s) in the last "
        f"{int(ACTIVITY_WINDOW_SECONDS // 60)} minutes: {format_paths(collision.shared_paths)}\n"
        "Neither of you announced this — it was detected from what you both actually edited.\n"
        f"Look: `curl $CCDB_API_URL/api/threads/{other}/messages?limit=30` · "
        f"talk: `POST $CCDB_API_URL/api/threads/{other}/message` · "
        "claim next time: `POST $CCDB_API_URL/api/claims`"
    )


def build_lounge_notice(collision: Collision) -> str:
    """The lounge line, which reaches every session's next turn for free."""
    first, second = collision.threads
    return (
        f"⚠️ auto-detected collision: threads {first} and {second} both wrote "
        f"{format_paths(collision.shared_paths)} in the last "
        f"{int(ACTIVITY_WINDOW_SECONDS // 60)} minutes. "
        "Whoever has commits or a PR continues; otherwise the earlier session continues. "
        "The other should push its branch and stand down."
    )
