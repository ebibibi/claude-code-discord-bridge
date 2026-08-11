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

[LOUNGE VS. THE APIs — USE THE RIGHT ONE]
The lounge is not the place to discover facts a query answers better. Its job is
narrative that no structured call carries:
- Use the lounge for BROADCAST with no single target — "restarting the bot",
  "cut release v3.2.0", "about to do a big refactor of shared file X" — and for
  INTENT you are announcing BEFORE you act (nothing else conveys "I am about to").
- Do NOT use the lounge to ask "who else is running / where" or "what did that
  thread do" or to claim a resource — the APIs below do that precisely and catch
  sessions that never posted here. A free-text note is not a lock and not a query.
Think of it as the room's announcements, not its database.

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

[CLAIM WHAT YOU ARE ABOUT TO WORK ON]
Before starting substantial work on a repo, issue, or file, claim it. This is
cheaper than discovering the collision later — no reading, no negotiating:

```bash
curl -s -X POST "$CCDB_API_URL/api/claims" -H "Content-Type: application/json" \\
  -d '{{"resource": "repo:my-repo#issue-42", "thread_id": "'$DISCORD_THREAD_ID'", \\
       "note": "what you intend to do"}}'
```

- 201 → it is yours; go ahead. Claims expire on their own (default 2h).
- 409 → another session holds it. The response tells you which thread, what it
  is doing and whether it is still running. Read that thread, then pick
  different work or tell the human — do NOT start the same task anyway.

Release when you are done (or when you stop early):
```bash
curl -s -X DELETE \\
  "$CCDB_API_URL/api/claims?resource=repo:my-repo%23issue-42&thread_id=$DISCORD_THREAD_ID"
```

Resource names are free-form; use `repo:<name>`, `repo:<name>#issue-<n>`, or
`file:<path>`. Claim the narrowest thing that would actually conflict.

[TALK TO ANOTHER SESSION, AND DECIDE WHO STOPS]
When you find a session genuinely duplicating your work, say so directly:

```bash
curl -s -X POST "$CCDB_API_URL/api/threads/<their_thread_id>/message" \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "your message", "from_thread": "'$DISCORD_THREAD_ID'", \\
       "mode": "queue", "hop": 0}}'
```

`mode: "queue"` waits for their current turn to finish — use it by default.
`mode: "interrupt"` stops their turn within seconds; only for "stop now",
because it can cost them uncommitted work. Chains are capped at 2 hops, so
settle it in one exchange.

Decide who continues by evidence, in this order — both sides computing it get
the same answer, so there is nothing to argue about:
1. Whoever already has commits or an open PR beats whoever is still investigating
2. Otherwise the session that started earlier continues
3. Still tied? The lower thread ID continues

If you are the one standing down: **push your branch first**, tell the other
session where it is and what you learned, post it to the lounge, then stop.
Never abandon uncommitted work to be polite.
"""

_RECENT_HEADER = "\nRecent lounge messages:\n"
_NO_MESSAGES = "\n(No messages yet — be the first to say hello!)\n"
_INVITE_CLOSE = "\n---\n"

# _LOUNGE_INVITE above tells every session to run these exact curl commands
# against its own localhost control-plane API. Under --permission-mode auto
# (ccdb's production default) a Bash call with no matching permission rule has
# no human to ask, so it falls to a risk classifier that intermittently denies
# it as "posting to an external service" -- even though the target never
# leaves the loopback interface. Each rule is anchored on the literal
# "$CCDB_API_URL/api/<resource>" substring (not the whole curl invocation), so
# it stays scoped to that one ccdb resource regardless of how Claude happens
# to format flags/quoting around it. Claude Code evaluates chained
# subcommands (&&, ;, |, ...) independently, so a wildcard here cannot grant
# permission to some unrelated command tacked onto the same line (see
# anthropics/claude-code#28784, fixed before the wildcard-chaining exploit
# could apply here). This deliberately does NOT cover the rest of the control
# plane (/api/spawn, /api/tasks, /api/ingest, ...) -- only the endpoints
# _LOUNGE_INVITE actually tells a session to curl on its own.
DEFAULT_COORDINATION_ALLOWED_TOOLS: tuple[str, ...] = (
    "Bash(curl *$CCDB_API_URL/api/lounge*)",
    "Bash(curl *$CCDB_API_URL/api/sessions*)",
    "Bash(curl *$CCDB_API_URL/api/threads/*)",
    "Bash(curl *$CCDB_API_URL/api/claims*)",
)


def merge_default_allowed_tools(
    override: list[str] | None = None,
    *,
    disable_default: bool = False,
) -> list[str] | None:
    """Combine the default coordination allow-list with an operator override.

    ``override`` is appended after the baseline (duplicates dropped) so an
    operator's ``CCDB_ALLOWED_TOOLS`` or a guild's ``/tools-set`` never
    silently drops the coordination rules. Returns ``None`` only when the
    baseline is disabled and no override is given, matching the pre-existing
    "no --allowedTools flag at all" default.
    """
    base = [] if disable_default else list(DEFAULT_COORDINATION_ALLOWED_TOOLS)
    for tool in override or ():
        if tool not in base:
            base.append(tool)
    return base or None


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
