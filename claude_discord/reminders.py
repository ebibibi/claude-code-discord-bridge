"""Reminder primitives — when to fire, and what to tell the session.

Pure functions only: no Discord, no database, no I/O.  Two reasons.  First, the
time arithmetic is where reminders actually break ("21:30" on a machine that is
asleep, an expiry that has already passed), so it has to be testable without a
bot.  Second, none of it may depend on the host OS — see ``docs`` on platform
support: the scheduler runs on Linux, macOS and Windows alike.

Two flavours of reminder exist, and the difference is not cosmetic:

* **plain** — say this at that time.  Delivered as a notification; no agent
  session is spawned, so it costs nothing but a Discord message.
* **conditional** — say this at that time *unless it is already done*.  This
  needs judgement, so a real session is spawned with
  :func:`build_conditional_prompt` and decides whether to speak at all.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

__all__ = [
    "DEFAULT_CHECK_INTERVAL_SECONDS",
    "build_conditional_prompt",
    "build_plain_reminder_text",
    "build_scheduling_notice",
    "extract_reminder_what",
    "parse_until",
    "parse_when",
    "repeat_interval_seconds",
]

# A one-shot reminder still has to store an interval (the column is NOT NULL).
# A day is the least surprising value: if a one-shot were ever re-enabled by
# hand it would fire at the same wall-clock time rather than immediately.
DEFAULT_CHECK_INTERVAL_SECONDS = 86400

_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_OFFSET_RE = re.compile(r"^\+?(\d+)([smhd])$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

_NAMED_INTERVALS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
}

_MAX_HOUR = 23
_MAX_MINUTE = 59


def _now_local(now: datetime | None) -> datetime:
    """Return *now* as an aware datetime in the host's local timezone."""
    return now if now is not None else datetime.now().astimezone()


def _parse_offset(raw: str) -> timedelta | None:
    """Parse ``"30m"`` / ``"+2h"`` into a positive timedelta, else None."""
    match = _OFFSET_RE.match(raw)
    if match is None:
        return None
    amount = int(match.group(1))
    if amount == 0:
        raise ValueError(f"Offset must be greater than zero: {raw!r}")
    return timedelta(seconds=amount * _UNIT_SECONDS[match.group(2)])


def _parse_iso(raw: str, reference: datetime) -> datetime | None:
    """Parse an ISO 8601 datetime, assuming the local zone when none is given."""
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=reference.tzinfo)
    return parsed


def parse_when(raw: str, *, now: datetime | None = None) -> datetime:
    """Resolve a human "when" into an absolute instant in the future.

    Accepts a wall-clock time (``"21:30"`` — the next occurrence, so a time
    that has already passed today means tomorrow), a relative offset
    (``"30m"``, ``"+2h"``, ``"3d"``) or an ISO 8601 datetime.

    Raises:
        ValueError: If the input is unparseable or already in the past.
    """
    reference = _now_local(now)
    text = (raw or "").strip()
    if not text:
        raise ValueError("A time is required (e.g. 21:30, 2h, 2026-08-08T09:00)")

    if match := _CLOCK_RE.match(text):
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > _MAX_HOUR or minute > _MAX_MINUTE:
            raise ValueError(f"Time out of range: {text!r} (use 00:00-23:59)")
        candidate = datetime.combine(reference.date(), time(hour, minute), reference.tzinfo)
        # "now" is never a useful reminder time, so treat it as tomorrow.
        return candidate if candidate > reference else candidate + timedelta(days=1)

    if (offset := _parse_offset(text)) is not None:
        return reference + offset

    if (parsed := _parse_iso(text, reference)) is not None:
        if parsed <= reference:
            raise ValueError(f"That moment is already in the past: {text!r}")
        return parsed

    raise ValueError(f"Cannot read {text!r} as a time (try 21:30, 2h, or 2026-08-08T09:00)")


def parse_until(raw: str | None, *, now: datetime | None = None) -> datetime | None:
    """Resolve an expiry. A bare date means the very end of that day.

    ``None`` means "no expiry" — the reminder lives until it is satisfied or
    cancelled.  A bare date is expanded to 23:59:59 because "until the 7th"
    colloquially includes the 7th; expanding it to midnight would silently
    drop the whole day.

    Raises:
        ValueError: If the input is unparseable or already in the past.
    """
    if raw is None:
        return None
    reference = _now_local(now)
    text = raw.strip()
    if not text:
        return None

    if _DATE_RE.match(text):
        day = datetime.fromisoformat(text).date()
        resolved = datetime.combine(day, time(23, 59, 59), reference.tzinfo)
    elif (offset := _parse_offset(text)) is not None:
        resolved = reference + offset
    elif (parsed := _parse_iso(text, reference)) is not None:
        resolved = parsed
    else:
        raise ValueError(f"Cannot read {text!r} as an expiry (try 2026-08-08 or 2d)")

    if resolved <= reference:
        raise ValueError(f"That expiry is already in the past: {text!r}")
    return resolved


def repeat_interval_seconds(every: str | None) -> int:
    """Translate a repeat spec (``"daily"``, ``"6h"``, ``None``) into seconds."""
    if every is None:
        return DEFAULT_CHECK_INTERVAL_SECONDS
    text = every.strip().lower()
    if text in _NAMED_INTERVALS:
        return _NAMED_INTERVALS[text]
    if (offset := _parse_offset(text)) is not None:
        return int(offset.total_seconds())
    raise ValueError(f"Cannot read {every!r} as a repeat interval (try daily, 6h, 30m)")


_CONDITIONAL_TEMPLATE = """\
[SCHEDULED REMINDER — verify first, speak only if needed]

You are a scheduled check, not a chat turn. The user asked to be reminded about
this only if it is still outstanding.

Verify whether it is already done:
{check}

Then act:
- **Already done** → stay silent. Post nothing at all.
- **Not done** → Remind the user in this thread, in their language. Be specific
  and immediately actionable — restate the deadline and the next step, not just
  "this is a reminder". What they wanted to be reminded of:
  {what}

Either way, finish by retiring this reminder so it cannot fire again:
`curl -s -X DELETE "$CCDB_API_URL/api/tasks/by-name/{task_name}"`
Skip the deletion only if this reminder is meant to repeat until satisfied and
it is still outstanding.

Use read-only checks. Do not change anything to make the condition true.

{marker} {what}\
"""

# Trailing marker so ``/reminders`` can show what a scheduled task is *about*
# without giving the generic scheduler table a reminder-specific column.
_WHAT_MARKER = "[reminder:what]"


def build_conditional_prompt(*, what: str, check: str, task_name: str) -> str:
    """Build the session prompt for a reminder that must verify before nagging.

    Raises:
        ValueError: If *what* or *check* is blank — a conditional reminder with
            nothing to check would nag unconditionally, which is worse than no
            reminder at all.
    """
    what_text = (what or "").strip()
    check_text = (check or "").strip()
    if not what_text:
        raise ValueError("A reminder needs something to remind about")
    if not check_text:
        raise ValueError("A conditional reminder needs a condition to check")
    return _CONDITIONAL_TEMPLATE.format(
        what=what_text, check=check_text, task_name=task_name, marker=_WHAT_MARKER
    )


def extract_reminder_what(prompt: str) -> str | None:
    """Recover the human subject of a conditional reminder from its prompt.

    Returns None for prompts that were not built by
    :func:`build_conditional_prompt` (any other scheduled task).
    """
    for line in reversed((prompt or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith(_WHAT_MARKER):
            return stripped[len(_WHAT_MARKER) :].strip() or None
    return None


_SCHEDULING_NOTICE = """\
## Scheduling Your Own Follow-Up
You can wake yourself up later in this thread instead of asking the user to \
remind you:
```
curl -s -X POST "$CCDB_API_URL/api/tasks" -H 'Content-Type: application/json' \\
  -d '{{"name": "remind-{thread_id}-<slug>", "prompt": "<what to do then>", \
"interval_seconds": 86400, "thread_id": {thread_id}, "run_at": "21:30", \
"one_shot": true}}'
```
`run_at` takes `"21:30"` (next occurrence), `"2h"`, or ISO 8601. Add \
`"until": "YYYY-MM-DD"` to a repeating task so it stops on its own, and \
`DELETE $CCDB_API_URL/api/tasks/by-name/<name>` to retire one early.
For a reminder that must stay quiet when the thing is already done, put the \
check in the prompt: verify first, post nothing if satisfied, and delete the \
task. Never claim you will follow up later without registering it — nothing \
else will wake you.\
"""


def build_scheduling_notice(thread_id: int) -> str:
    """Tell a session it can schedule its own future runs.

    Injected into every session's system context.  The capability existed long
    before this notice did, and sessions kept reinventing it with host cron or
    external schedulers because nothing told them it was there.
    """
    return _SCHEDULING_NOTICE.format(thread_id=thread_id)


def build_plain_reminder_text(what: str) -> str:
    """Build the message body for an unconditional reminder."""
    text = (what or "").strip()
    if not text:
        raise ValueError("A reminder needs something to remind about")
    return f"⏰ {text}"
