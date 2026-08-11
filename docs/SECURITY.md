# Security Model

## Threat Model

claude-code-discord-bridge spawns Claude Code CLI subprocesses that can execute arbitrary code on the host machine (read/write files, run commands, make network requests). This is **by design** — Claude Code's value comes from its ability to interact with the development environment.

The bridge's security goal is:

> **Ensure that only authorized users can trigger Claude Code sessions, and that the bridge layer itself does not introduce additional attack surfaces beyond what Claude Code CLI already exposes.**

### What We Protect Against

| Threat | Mitigation |
|--------|-----------|
| Unauthorized users invoking Claude | `allowed_user_ids` allowlist in `ClaudeChatCog` and `SkillCommandCog` |
| Shell injection via user prompts | `create_subprocess_exec` (no shell), `--` separator before prompt arg |
| Flag injection via prompts | `--` separator prevents `-p`, `--resume` etc. in prompt text |
| Session hijacking via crafted IDs | Strict regex validation: `^[a-f0-9\-]+$` |
| Skill name injection | Strict regex validation: `^[\w-]+$` |
| Path traversal via ingest attachments | Client filenames reduced to a safe basename, then re-checked against the ingest root inside the function that makes each filesystem call (`_contained_path`, and the same test written out in `_unique_path`) |
| Zip slip via ingest archives | Each archive member is resolved and refused if it escapes the extraction directory or the ingest root |
| Secrets leaking to Claude subprocess | `_STRIPPED_ENV_KEYS` removes `DISCORD_BOT_TOKEN`, `CLAUDECODE`, etc. from subprocess env |
| Claude reading Discord secrets via Bash tool | Environment stripping prevents `echo $DISCORD_BOT_TOKEN` in Claude's Bash |
| Nesting detection bypass | `CLAUDECODE` env var stripped — subprocess won't think it's already inside Claude Code |

### What We Do NOT Protect Against

| Scenario | Why |
|----------|-----|
| Claude Code accessing host filesystem | This is Claude Code's core functionality — restricting it defeats the purpose |
| Claude Code making network requests | Same as above — Claude Code needs internet access for web search, API calls, etc. |
| Claude Code modifying its own config | This is expected behavior (CLAUDE.md, memory files, etc.) |
| Discord server admin abuse | If someone has admin on your Discord server, they already have control |
| Physical access to the host | Out of scope — standard server security applies |

**The security boundary is at the Discord layer, not the CLI layer.** Once a session starts, Claude Code has full CLI-level access. The bridge's job is to ensure only the right person can start sessions.

## Input Validation

### Prompt Handling (runner.py)

```python
# All arguments passed as a list — no shell interpolation
args = [self.command, "-p", "--output-format", "stream-json", ...]

# -- separator prevents the prompt from being interpreted as flags
args.append("--")
args.append(prompt)

# Spawned without shell
self._process = await asyncio.create_subprocess_exec(*args, ...)
```

Why this matters:
- A prompt like `--dangerously-skip-permissions` won't be interpreted as a flag
- A prompt like `$(rm -rf /)` won't be shell-expanded
- `create_subprocess_exec` passes arguments directly to the exec syscall

### Session ID Validation (runner.py)

```python
if not re.match(r"^[a-f0-9\-]+$", session_id):
    raise ValueError(f"Invalid session_id format: {session_id!r}")
```

Session IDs come from Claude Code CLI output and are stored in SQLite. Before passing back via `--resume`, they're validated against a strict hex-and-hyphens pattern.

### Skill Name Validation (skill_command.py)

```python
if not re.match(r"^[\w-]+$", name):
    await interaction.response.send_message(f"Invalid skill name: `{name}`", ephemeral=True)
    return
```

Skill names are passed to Claude Code as `/{name}`. The regex ensures only alphanumeric characters, underscores, and hyphens are allowed.

### Ingest Attachment Paths (api_server.py)

`POST /api/ingest` accepts base64 attachments from untrusted external clients and writes them to disk under an ingest root, so both the filename and any zip member name are attacker-controlled. Two independent guards apply.

First, the filename is reduced to a safe basename:

```python
name = os.path.basename(str(raw or "")).strip()
name = _UNSAFE_FILENAME_RE.sub("_", name).lstrip(".")
return name or f"attachment_{index}"
```

This strips directory components, replaces anything outside `[\w.\-]`, and drops leading dots so an attachment can't masquerade as a dotfile.

Second, containment is re-established immediately before the filesystem call:

```python
root = os.path.realpath(str(self._ingest_root()))
resolved = os.path.realpath(str(path))
if resolved != root and not resolved.startswith(root + os.sep):
    return None
```

Why both:
- The basename sanitiser lives far from the `open()` calls it protects. The containment test re-checks *at the sink*, so every path ccdb opens, stats or writes under the ingest tree is verified — a future refactor can't silently bypass it
- Returning `None` is a refusal, not a fallback path: callers skip the file rather than write it somewhere else
- `_unique_path` builds its candidate list up front and re-checks *every* derived variant (`name_2.ext`, `name_3.ext`, …) before touching it, because those names are built from the same untrusted input
- Running out of candidates is a refusal too. After 1000 same-named files `_unique_path` returns `None` rather than falling back to a `uuid`-suffixed name: 1000 identical filenames in one request is not a real export, and a random name nothing else can predict is worse than a clear error. A direct attachment becomes a `400`; a zip member is skipped
- Comparing against `root + os.sep` — not bare `root` — is what stops a sibling directory like `ingest-evil` from passing a prefix test against `ingest`
- The check is deliberately spelled `os.path.realpath` + `startswith` rather than `Path.resolve()` + `relative_to()`. The two are equivalent, but only the former is recognised as a path sanitiser by CodeQL; with the pathlib spelling the hardening was invisible to the very tool meant to verify it
- For the same reason the test is *written out* in `_unique_path` instead of delegating to `_contained_path`. The two are identical, but a guard that lives behind a call boundary does not propagate for static analysis: with the delegated version CodeQL still reported both `exists()` calls as live path injections. Keeping the `realpath` + prefix test in the same function as the filesystem call it protects makes the guarantee local — to a reader and to the analyser alike. `_contained_path` remains for the paths handed to `hash_files()`, where the delegation *is* recognised

Zip attachments are extracted member by member, and a member is skipped if it resolves outside the extraction directory or fails the ingest-root check.

Extraction never destroys the upload it came from. The original is deleted only once extraction has actually produced files: `zipfile.is_zipfile()` matches an end-of-central-directory record near the *end* of a file, so a large opaque binary — a Windows `.evtx` log, a dump, a capture — can carry a well-formed empty EOCD by chance and be read as an archive it isn't. Expanding such a file yields zero members, and unlinking it then destroyed the attachment while `attachments_saved` still reported success. A zip that yields nothing (empty, refused, or malformed) is kept as it arrived — replacing a file with nothing is never an improvement.

## Environment Isolation

### Stripped Environment Variables (runner.py)

```python
_STRIPPED_ENV_KEYS = frozenset(
    {
        "CLAUDECODE",  # Nesting detection
        "DISCORD_BOT_TOKEN",  # Bot authentication
        "DISCORD_TOKEN",  # Alternative token var
        "API_SECRET_KEY",  # API authentication
        "CCDB_AGUI_URL",  # AG-UI run endpoint
        "CCDB_AGUI_TOKEN",  # AG-UI bearer token
        "CCDB_TEAMS_APP_PASSWORD",  # Teams bot credential
        "CCDB_TEAMS_QUEUE_URL",  # Teams relay queue connection string
        "CCDB_API_URL",  # Re-added per session, scoped to this subprocess's own API port
        "CCDB_API_SECRET",  # Re-added per session alongside CCDB_API_URL
        "CCDB_ZAI_ENV_FILE",  # Path to the Z.ai credential file; consumed, never forwarded
    }
)
```

These variables are removed from the subprocess environment before spawning Claude Code:

1. **DISCORD_BOT_TOKEN / DISCORD_TOKEN**: Prevents Claude Code from reading the Discord token via its Bash tool
2. **CLAUDECODE**: Claude Code uses this to detect nesting. Stripping it ensures the subprocess runs as a fresh top-level instance
3. **API_SECRET_KEY**: If the host bot exposes a REST API, this key shouldn't leak to Claude
4. **CCDB_AGUI_URL / CCDB_AGUI_TOKEN**: The remote AG-UI endpoint and its bearer token are ccdb's own routing config, not something a Claude/Codex session's Bash tool should be able to read or reuse
5. **CCDB_TEAMS_APP_PASSWORD / CCDB_TEAMS_QUEUE_URL**: Same reasoning for the Teams frontend's bot credential and relay queue connection string
6. **CCDB_API_URL / CCDB_API_SECRET**: Stripped from the inherited environment, then set explicitly per session scoped to that session's own local API port — a session never receives another session's API credential
7. **CCDB_ZAI_ENV_FILE**: The *path* to the Z.ai credential file must not reach the CLI's Bash tool; `ZaiRunner` reads the file, merges its contents into the subprocess environment, then pops the path itself before spawning

### Z.ai credential isolation (zai_runner.py)

A Z.ai thread runs the same Claude Code CLI as the `claude` backend, so `ZaiRunner` cannot rely on
a different binary to keep the two credential sets apart. Instead, before applying the Z.ai
credential file it pops `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the subprocess
environment — the two variables the direct-Anthropic backend passes through (see below) — so a
Z.ai session can never inherit, or silently fall back to, direct Anthropic credentials. Losing the
Z.ai credential file therefore fails as an auth error against Z.ai, not as a quiet switch to
Anthropic billing.

### What's NOT Stripped

General environment variables (PATH, HOME, ANTHROPIC_API_KEY, etc.) are passed through because Claude Code needs them to function. The `ANTHROPIC_API_KEY` is intentionally available — Claude Code uses it for API calls. If you need to restrict which API key Claude Code uses, configure it via Claude Code's own settings, not this bridge. The Z.ai backend is the one exception: it strips `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` for its own threads only (see above).

## Authorization Model

### User-Level Authorization

```python
class ClaudeChatCog(commands.Cog):
    def __init__(self, ..., allowed_user_ids: set[int] | None = None):
        self._allowed_user_ids = allowed_user_ids

    async def on_message(self, message):
        if message.author.bot:
            return
        if self._allowed_user_ids is not None and message.author.id not in self._allowed_user_ids:
            return
```

- When `allowed_user_ids` is set: only listed Discord user IDs can invoke Claude
- When `allowed_user_ids` is `None`: all users in the channel can invoke Claude (for trusted private servers)
- The same check applies to `SkillCommandCog`

### Channel-Level Authorization

Both Cogs only respond to messages in the configured channel (`channel_id`) and its child threads. Messages in other channels are silently ignored.

### Bot Messages

`message.author.bot` check ensures bot messages (including webhook messages) don't trigger Claude sessions. This prevents infinite loops if Claude's output triggers another bot.

## Webhook Security (Consumer Cog Pattern)

When building custom Cogs that respond to webhooks (like EbiBot's docs-sync), follow this pattern:

```python
# Only respond to webhook messages
if not message.webhook_id:
    return

# Fixed trigger string — no arbitrary command execution
if message.content.strip() != "🔄 expected-trigger":
    return

# Hardcoded behavior — webhook cannot inject commands
prompt = HARDCODED_PROMPT  # Server-side, not from webhook
```

Key principles:
1. **Check `webhook_id`** — distinguishes webhooks from regular users
2. **Fixed trigger strings** — webhook cannot specify what to do, only trigger predefined actions
3. **Hardcoded prompts** — all Claude Code prompts are defined server-side, never from webhook content

## Database Security

- SQLite database stores `thread_id` → `session_id` mappings only
- No user data, no messages, no secrets stored
- Parameterized queries throughout (`?` placeholders, no string formatting)
- `cleanup_old()` method for age-based data removal

## Deployment Recommendations

1. **Private Discord server**: Run the bot on a server only you have access to
2. **Dedicated channel**: Use a specific channel for Claude interactions, not a general chat
3. **Set `allowed_user_ids`**: Always set this in production — don't rely solely on channel permissions
4. **Review Claude Code permissions**: Configure `permission_mode` and `allowed_tools` to restrict Claude Code's capabilities as needed
5. **Don't use `dangerously_skip_permissions`**: This flag exists for power users who understand the implications. It disables Claude Code's built-in safety prompts
6. **Monitor the bot**: Check logs regularly. Claude Code sessions are logged with timing and cost data
7. **Keep dependencies updated**: `uv lock --upgrade-package claude-code-discord-bridge && uv sync`

## Security Audit Checklist

Before merging changes to `runner.py`, `_run_helper.py`, `ext/api_server.py`, or any Cog:

- [ ] No `shell=True` in any subprocess call
- [ ] `--` separator present before user-supplied arguments
- [ ] All external input validated (session IDs, skill names, channel IDs)
- [ ] Any new filesystem write under the ingest root goes through `_contained_path` / `_unique_path`
- [ ] Containment checks stay in the function that makes the filesystem call — don't "clean up" an inline guard into a helper, it stops propagating for CodeQL
- [ ] `_STRIPPED_ENV_KEYS` covers any new secret variables
- [ ] No string formatting in SQL queries (use `?` placeholders)
- [ ] `allowed_user_ids` check present in any new message handler
- [ ] No new `os.system()`, `subprocess.run(shell=True)`, or `eval()` calls
