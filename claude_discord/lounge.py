"""AI Lounge prompt builder.

Generates the lounge context block injected at the start of each Claude
session.  The lounge is a casual shared space — like an AI breakroom —
where concurrent sessions leave notes for each other and for the humans
watching the Discord channel.
"""

from __future__ import annotations

from .database.lounge_repo import LoungeMessage

# The invitation block tells Claude *what* the lounge is, *how* to post,
# and sets the expectation that posting at session start is mandatory.
_LOUNGE_INVITE = """\
[AI LOUNGE — welcome to the breakroom]

This is the AI Lounge — a shared space where concurrent Claude sessions
leave notes for each other and for the humans watching the Discord channel.

[REQUIRED] Before starting any work, post a one-liner to the lounge.
This is your session-start announcement. Keep it short and in your own words.

Examples:
- "Investigating a bug in the XXX repo. Looks a bit tricky."
- "PR review request came in, heading over to check it."
- "All tests are failing... figuring out what happened."
- "Just fixing a config file, should be quick."

When you finish, leave a closing note too (this serves as your session-end signal):
- "Done! All tests passing." / "Took longer than expected..."

Post command:
```bash
curl -s -X POST "$CCDB_API_URL/api/lounge" \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "your note here", "label": "your nickname", \\
       "thread_id": "'$DISCORD_THREAD_ID'"}}'
```

Labels are free-form. Examples: "bug-hunter", "night-shift", "frontend", "careful"

[READ BEFORE DESTRUCTIVE OPERATIONS]
Before bot restarts, force pushes, DB operations, or anything that affects all sessions:
1. Check the recent lounge messages below
2. If another session is actively working, wait for it to finish or announce your intent
3. Only proceed if the coast is clear — report before and after

This is the lounge's most critical use. Read it to make decisions, not just to write.

[LOOK AT WHAT OTHER SESSIONS ARE DOING]
A lounge note tells you a thread ID. These two endpoints let you go and look:

```bash
# Who else is alive, where are they working, what did they last announce?
curl -s "$CCDB_API_URL/api/sessions?exclude_thread=$DISCORD_THREAD_ID"

# Read another thread's actual conversation (thread_id from the call above)
curl -s "$CCDB_API_URL/api/threads/<thread_id>/messages?limit=30"
```

Use them when a lounge note sounds like your task, when you are about to touch a
shared repo, or when you suspect a session that never posted here. Sessions with
``"state": "running"`` have a turn in flight right now; ``working_dir`` tells you
whether you would collide. Reading is free and has no side effects — when in
doubt, look before you edit.
"""

_RECENT_HEADER = "\nRecent lounge messages:\n"
_NO_MESSAGES = "\n(No messages yet — be the first to say hello!)\n"
_INVITE_CLOSE = "\n---\n"


def build_lounge_prompt(
    recent_messages: list[LoungeMessage],
    *,
    current_thread_id: int | None = None,
) -> str:
    """Return the full lounge context string to prepend to Claude's prompt.

    Args:
        recent_messages: Recent messages from LoungeRepository.get_recent(),
                         in chronological order (oldest first).
        current_thread_id: The Discord thread ID of the current session.
                           Messages from this thread are annotated with
                           ``[this thread]`` so the AI can distinguish its
                           own earlier posts from other sessions' posts
                           (critical after context compaction).
    """
    parts = [_LOUNGE_INVITE]

    if recent_messages:
        parts.append(_RECENT_HEADER)
        for msg in recent_messages:
            # Truncate the timestamp to HH:MM for readability (posted_at is
            # "YYYY-MM-DD HH:MM:SS" from SQLite datetime('now', 'localtime')).
            timestamp = msg.posted_at[11:16] if len(msg.posted_at) >= 16 else msg.posted_at
            # Annotate messages from the current thread so the AI knows
            # "this was me in a previous context window, not another session".
            marker = ""
            if (
                current_thread_id is not None
                and msg.thread_id is not None
                and msg.thread_id == current_thread_id
            ):
                marker = " [this thread]"
            parts.append(f"  [{timestamp}] {msg.label}{marker}: {msg.message}")
    else:
        parts.append(_NO_MESSAGES)

    parts.append(_INVITE_CLOSE)
    return "\n".join(parts)
