# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Use Claude Code on your phone. Multiple threads. All at once. Real development included.**

Open Claude Code from your smartphone's Discord app, spin up multiple threads, and run parallel development sessions — all without touching a keyboard. Each Discord thread becomes a fully isolated Claude Code session. Work on a feature in one thread, review a PR in another, and run a background task in a third — simultaneously. The bridge handles all the coordination so sessions never clobber each other.

**No API key required. No per-token billing.** ccdb runs on top of Claude Code CLI, which is included with your [Claude Pro/Max subscription](https://claude.ai/pricing) — a flat monthly fee with no usage surprises. Unlike API-based integrations that charge per token, ccdb lets your whole team use Claude through Discord at predictable cost.

**[日本語](docs/ja/README.md)** | **[简体中文](docs/zh-CN/README.md)** | **[한국어](docs/ko/README.md)** | **[Español](docs/es/README.md)** | **[Português](docs/pt-BR/README.md)** | **[Français](docs/fr/README.md)**

> **Disclaimer:** This project is not affiliated with, endorsed by, or officially connected to Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic, PBC. This is an independent open-source tool that interfaces with the Claude Code CLI.

> **Built entirely by Claude Code.** This entire codebase — architecture, implementation, tests, documentation — was written by Claude Code itself. The human author provided requirements and direction via natural language. See [How This Project Was Built](#how-this-project-was-built).

---

## The Big Idea: Parallel Sessions Without Fear

When you send tasks to Claude Code in separate Discord threads, the bridge does four things automatically:

1. **Concurrency notice injection** — Every session's system prompt includes mandatory instructions: create a git worktree, work only inside it, never touch the main working directory directly.

2. **Active session registry** — Each running session knows about the others. If two sessions are about to touch the same repo, they can coordinate rather than conflict.

3. **AI Lounge** — A session-to-session "breakroom" injected into every prompt. Before starting, each session reads recent lounge messages to see what other sessions are doing. Before disruptive operations (force push, bot restart, DB drop), sessions check the lounge first so they don't stomp on each other's work.

```
Thread A (feature)   ──→  Claude Code (worktree-A)  ─┐
Thread B (PR review) ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Thread C (docs)      ──→  Claude Code (worktree-C)  ─┘    "A: auth refactor in progress"
                                                           "B: PR #42 review done"
                                                           "C: updating README"
```

No race conditions. No lost work. No merge surprises.

---

## What You Can Do

### Interactive Chat (Mobile / Desktop)

Use Claude Code from anywhere Discord runs — phone, tablet, or desktop. Each message creates or continues a thread, mapping 1:1 to a persistent Claude Code session.

### Parallel Development

Open multiple threads simultaneously. Each is an independent Claude Code session with its own context, working directory, and git worktree. Useful patterns:

- **Feature + review in parallel**: Start a feature in one thread while Claude reviews a PR in another.
- **Multiple contributors**: Different team members each get their own thread; sessions stay aware of each other via the AI Lounge.
- **Experiment safely**: Try an approach in thread A while keeping thread B on stable code.

### Scheduled Tasks (SchedulerCog)

Register periodic Claude Code tasks from a Discord conversation or via REST API — no code changes, no redeploys. Tasks are stored in SQLite and run on a configurable schedule. Claude can self-register tasks during a session using `POST /api/tasks`.

```
/skill name:goodmorning         → runs immediately
Claude calls POST /api/tasks    → registers a periodic task
SchedulerCog (30s master loop)  → fires due tasks automatically
```

### CI/CD Automation

Trigger Claude Code tasks from GitHub Actions via Discord webhooks. Claude runs autonomously — reads code, updates docs, creates PRs, enables auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Real example:** On every push to `main`, Claude analyzes the diff, updates English + Japanese documentation, creates a bilingual PR, and enables auto-merge. Zero human interaction.

### Session Sync

Already use Claude Code CLI directly? Sync your existing terminal sessions into Discord threads with `/sync-sessions`. Backfills recent conversation messages so you can continue a CLI session from your phone without losing context.

### AI Lounge

A shared "breakroom" channel where all concurrent sessions announce themselves, read each other's updates, and coordinate before disruptive operations.

Each Claude session receives the lounge context automatically via `--append-system-prompt` — injected as ephemeral system context rather than as part of the conversation history. This prevents the context from accumulating across turns, which would otherwise cause "Prompt is too long" errors in long-running sessions. The injected context includes: recent messages from other sessions, plus the rule to check before doing anything destructive.

```bash
# Sessions post their intentions before starting:
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "Starting auth refactor on feature/oauth — worktree-A", "label": "feature dev"}'

# Read recent lounge messages (also injected into each session automatically):
curl "$CCDB_API_URL/api/lounge"
```

The lounge channel doubles as a human-visible activity feed — open it in Discord to see at a glance what every active Claude session is currently doing.

### Programmatic Session Creation

Spawn new Claude Code sessions from scripts, GitHub Actions, or other Claude sessions — without Discord message interaction.

```bash
# From another Claude session or a CI script:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Run security scan on the repo", "thread_name": "Security Scan"}'
# Returns immediately with the thread ID; Claude runs in the background
```

Claude subprocesses receive `DISCORD_THREAD_ID` as an environment variable, so a running session can spawn child sessions to parallelize work.

### Startup Resume

If the bot restarts mid-session, interrupted Claude sessions are automatically resumed when the bot comes back online. Sessions are marked for resume in three ways:

- **Automatic (upgrade restart)** — `AutoUpgradeCog` snapshots all active sessions just before a package upgrade restart and marks them automatically.
- **Automatic (any shutdown)** — `ClaudeChatCog.cog_unload()` marks all mid-run sessions whenever the bot shuts down via any mechanism (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manual** — Any session can call `POST /api/mark-resume` directly.

---

## Features

### Interactive Chat

#### 🔗 Session Basics
- **Chat-only mode** — When `CHAT_ONLY_CHANNEL_IDS` includes a channel, only Claude's text responses are shown; tool embeds, thinking blocks, session start/complete embeds, and todo lists are hidden. Permission requests and `AskUserQuestion` are always shown. Ideal for public channels where non-technical users are watching.
- **Thread = Session** — 1:1 mapping between Discord thread and Claude Code session
- **Session persistence** — Resume conversations across messages via `--resume`
- **Concurrent sessions** — Multiple parallel sessions with configurable limit
- **Stop without clearing** — `/stop` halts a session while preserving it for resume
- **Session interrupt** — Sending a new message to an active thread sends SIGINT to the running session and starts fresh with the new instruction; no manual `/stop` needed
- **Auto-rename threads** — When `THREAD_AUTO_RENAME=true`, each new thread is automatically renamed with a Claude-generated title derived from the first message (background task, never delays session start)

#### 📡 Real-time Feedback
- **Real-time status** — Emoji reactions: 🧠 thinking, 🛠️ reading files, 💻 editing, 🌐 web search
- **Streaming text** — Intermediate assistant text appears as Claude works
- **Tool result embeds** — Live tool call results with elapsed time shown immediately (0s) and ticking up every 5s; single-line outputs shown inline, multi-line outputs collapsed behind an expand button
- **Extended thinking** — Reasoning shown as spoiler-tagged embeds (click to reveal)
- **Thread dashboard** — Live pinned embed showing which threads are active vs. waiting; owner @-mentioned when input is needed

#### 🤝 Human-in-the-Loop
- **Interactive questions** — `AskUserQuestion` renders as Discord Buttons or Select Menu; session resumes with your answer; buttons survive bot restarts
- **Plan Mode** — When Claude calls `ExitPlanMode`, a Discord embed shows the full plan with Approve/Cancel buttons; Claude proceeds only after approval; auto-cancel on 5-minute timeout
- **Tool permission requests** — When Claude needs permission to execute a tool, Discord shows Allow/Deny buttons with the tool name and input; auto-deny after 2 minutes
- **MCP Elicitation** — MCP servers can request user input via Discord (form-mode: up to 5 Modal fields from JSON schema; url-mode: URL button + Done confirmation); 5-minute timeout
- **Live TodoWrite progress** — When Claude calls `TodoWrite`, a single Discord embed is posted and edited in-place on each update; shows ✅ completed, 🔄 active (with `activeForm` label), ⬜ pending items

#### 📊 Observability
- **Token usage** — Cache hit rate and token counts shown in session-complete embed
- **Context usage** — Context window percentage (input + cache tokens, excluding output) and remaining capacity until auto-compact shown in session-complete embed; ⚠️ warning when above 83.5%
- **Compact detection** — Notifies in-thread when context compaction occurs (trigger type + token count before compact)
- **Hard stall notification** — Thread message after no activity (extended thinking or context compression); resets automatically when Claude resumes. Thresholds are model-aware: 30 s for standard models, 120 s for Opus (which has longer thinking pauses)
- **Timeout notifications** — Embed with elapsed time and resume guidance on timeout
- **StatusLine display** — When Claude configures a `statusLine` (via `/statusline-setup`), the current status is shown in Discord after each session as a concise, always-visible indicator
- **Thread inbox** — When `THREAD_INBOX_ENABLED=true`, the dashboard shows a persistent 📬 inbox section: after each session ends, Claude classifies the final message (`waiting` / `done` / `ambiguous`) via a lightweight `claude -p` call; threads awaiting your reply survive bot restarts and are surfaced until you respond

#### 🔌 Input & Skills
- **Attachment support** — Text files auto-appended to prompt (up to 5 files, 200 KB each / 500 KB total; oversized files are truncated with a notice rather than skipped); images sent as Discord CDN URLs via `--input-format stream-json` (up to 4 × 5 MB); long pasted messages that Discord auto-converts to file attachments (without `content_type`) are handled via extension-based detection
- **On-demand file delivery** — Ask Claude to "send me" or "attach" a file and it writes the path to `.ccdb-attachments`; the bot reads it and delivers the file as a Discord attachment when the session completes
- **Skill execution** — `/skill` command with autocomplete, optional args, in-thread resume; skills from installed plugins are also auto-discovered
- **Hot reload** — New skills added to `~/.claude/skills/` are picked up automatically (60s refresh, no restart)

### Concurrency & Coordination
- **Worktree instructions auto-injected** — Every session prompted to use `git worktree` before touching any file
- **Automatic worktree cleanup** — Session worktrees (`wt-{thread_id}`) are removed automatically at session end and on bot startup; dirty worktrees are never auto-removed (safety invariant)
- **Active session registry** — In-memory registry; each session sees what the others are doing
- **AI Lounge** — Shared "breakroom" channel; context injected via `--append-system-prompt` (ephemeral, never accumulates in history) so long sessions never hit "Prompt is too long"; sessions post intentions, read each other's status, and check before disruptive operations; humans see it as a live activity feed
- **Coordination channel** — `COORDINATION_CHANNEL_ID` env var is used as the default fallback for the AI Lounge channel (no separate bot-side lifecycle events)

### Scheduled Tasks
- **SchedulerCog** — SQLite-backed periodic task executor with a 30-second master loop
- **Self-registration** — Claude registers tasks via `POST /api/tasks` during a chat session
- **No code changes** — Add, remove, or modify tasks at runtime
- **Enable/disable** — Pause tasks without deleting them (`PATCH /api/tasks/{id}`)

### CI/CD Automation
- **Webhook triggers** — Trigger Claude Code tasks from GitHub Actions or any CI/CD system
- **Auto-upgrade** — Automatically update the bot when upstream packages are released
- **DrainAware restart** — Waits for active sessions to finish before restarting
- **Auto-resume marking** — Active sessions are automatically marked for resume on any shutdown (upgrade restart via `AutoUpgradeCog`, or any other shutdown via `ClaudeChatCog.cog_unload()`); on restart Claude reports its previous state and re-confirms with the user before resuming any implementation work
- **Restart approval** — Optional gate to confirm upgrades; approve via ✅ reaction in the upgrade thread or via button posted to the parent channel; the button re-posts itself at the bottom as new messages arrive so it stays visible
- **Manual upgrade trigger** — `/upgrade` slash command lets authorised users trigger the upgrade pipeline directly from Discord (opt-in via `slash_command_enabled=True`)

### Session Management
- **Built-in help** — `/help` shows all available slash commands and basic usage (ephemeral, only visible to the caller)
- **Session sync** — Import CLI sessions as Discord threads (`/sync-sessions`); `/sync-settings` to view or change sync preferences (thread style, time window, minimum results)
- **Session list** — `/sessions` with filtering by origin (Discord / CLI / all) and time window
- **Session resume** — `/resume` shows a select menu of recent sessions (up to 25) and resumes the selected one in a new thread; works from any channel or thread — always creates a new thread in the configured main channel
- **Resume info** — `/resume-info` shows the CLI command to continue the current session in a terminal (thread-only)
- **Clear session** — `/clear` resets the Claude Code session for the current thread, starting fresh without creating a new thread
- **Startup resume** — Interrupted sessions restart automatically after any bot reboot; `AutoUpgradeCog` (upgrade restarts) and `ClaudeChatCog.cog_unload()` (all other shutdowns) mark them automatically, or use `POST /api/mark-resume` manually
- **Programmatic spawn** — `POST /api/spawn` creates a new Discord thread + Claude session from any script or Claude subprocess; returns non-blocking 201 immediately after thread creation
- **Thread ID injection** — `DISCORD_THREAD_ID` env var is passed to every Claude subprocess, enabling sessions to spawn child sessions via `$CCDB_API_URL/api/spawn`
- **Worktree management** — `/worktree-list` shows all active session worktrees with clean/dirty status; `/worktree-cleanup` removes orphaned clean worktrees (supports `dry_run` preview)
- **Runtime model switching** — `/model-show` displays the current global model and per-thread session model; `/model-set` changes the model for all new sessions without restart
- **Runtime tool permissions** — `/tools-show` displays the current allowed tools; `/tools-set` opens a select menu to toggle tools on/off; `/tools-reset` reverts to `.env` default — all without restart
- **Context usage** — `/context` shows context window percentage with a visual progress bar; ⚠️ warning when nearing the 83.5% autocompact threshold; ephemeral (only visible to the caller)
- **Rate limit usage** — `/usage` shows Claude API rate limit utilization with percentage bar and time-until-reset countdown for 5-hour and 7-day windows; ⚠️ flag when utilization ≥ 80%
- **Conversation rewind** — `/rewind` shows a select menu of past user turns and truncates the session JSONL at the chosen point, removing that message and everything after it so the session resumes from the exact state before that turn; keeps all working files Claude created; useful when a session has gone off-track
- **Conversation fork** — `/fork` branches the current thread into a new thread that continues from the same session state via `--fork-session`, creating a truly independent session copy; lets you explore a different direction without affecting the original

### Security
- **No shell injection** — `asyncio.create_subprocess_exec` only, never `shell=True`
- **Session ID validation** — Strict regex before passing to `--resume`
- **Flag injection prevention** — `--` separator before all prompts
- **Secret isolation** — Bot token stripped from subprocess environment
- **User authorization** — `allowed_user_ids` restricts who can invoke Claude
- **Log injection prevention** — User-provided API values are sanitized (newlines stripped) before writing to logs

---

## Quick Start — Claude in Discord in 5 Minutes

**Prerequisites:** Python 3.10+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

**Platform support:** Primarily developed and tested on **Linux**. macOS and Windows are supported and pass CI, but receive less real-world testing — bug reports welcome.

### Step 1 — Create a Discord Bot (one-time, ~2 minutes)

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. Navigate to **Bot** → enable **Message Content Intent** under Privileged Gateway Intents
3. Copy the bot **Token**
4. Go to **OAuth2 → URL Generator**: Scopes `bot` + `applications.commands`, Permissions: Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. Open the generated URL → invite the bot to your server

### Step 2 — Run the Setup Wizard

No cloning or `.env` editing required — the wizard does it for you:

```bash
# With uvx (no install needed):
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# Or after cloning:
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

The wizard will:
1. Validate your bot token against the Discord API
2. **Automatically list available channels** — just pick a number (no ID copying)
3. Ask for your working directory and model preference
4. Write `.env` and offer to start the bot immediately

```
╔══════════════════════════════════════════════════════╗
║          ccdb setup — interactive wizard             ║
╚══════════════════════════════════════════════════════╝

Step 1 — Claude Code CLI
  ✅  claude found

Step 2 — Discord Bot Token
  Bot Token: [paste here]
  Validating token… ✅  Logged in as MyBot#1234

Step 3 — Discord Channel ID
  Fetching channels via Discord API… ✅  Found 5 text channel(s)

   1. #general        (My Server)
   2. #claude-code    (My Server)
   3. #dev            (My Server)
   ...

  Select channel [1-5]: 2
  ✅  #claude-code (123456789012345678)

  ...

  ✅  Written: .env
  Start the bot now? [Y/n]: y
```

### Start / Stop

```bash
ccdb start    # start the bot (reads .env in current dir)
ccdb start --env /path/to/.env   # custom .env location
```

Send a message in the configured channel — Claude will reply in a new thread.

### Running as a systemd Service (Production)

For production deployments, run the bot under systemd so it starts on boot and auto-restarts on failure.

The repo ships a ready-to-adapt template (`discord-bot.service`) and a pre-start script (`scripts/pre-start.sh`). Copy and customize them:

```bash
# 1. Edit the service file — replace /home/ebi and User=ebi with your paths/user
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service

# 2. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service

# 3. Check status
sudo systemctl status mybot.service
journalctl -u mybot.service -f
```

**What `scripts/pre-start.sh` does** (runs as `ExecStartPre` before the bot process):

1. **`git pull --ff-only`** — pulls the latest code from `origin main`
2. **`uv sync`** — keeps dependencies in sync with `uv.lock`
3. **Import validation** — verifies that `claude_discord.main` imports cleanly
4. **Auto-rollback** — if import fails, reverts to the previous commit and retries; posts a Discord webhook notification on failure or success
5. **Worktree cleanup** — removes stale git worktrees left by crashed sessions

The script detects the repository root dynamically (via `readlink -f` on `$0`), so it works for any user regardless of where they cloned the repo — no path editing needed in the script itself. It also auto-discovers the `uv` binary from `PATH`; override via `CCDB_UV_BIN` env var if needed.

The script requires the `DISCORD_WEBHOOK_URL` variable in `.env` for failure notifications (optional — the script works without it).

### Custom Cogs (Extend Without Forking)

Add your own features by dropping Python files into a directory — no fork, no subclass, no package needed:

```bash
ccdb start --cogs-dir ./my-cogs/
# Or: CUSTOM_COGS_DIR=./my-cogs ccdb start
```

Each `.py` file in the directory must expose an `async def setup(bot, runner, components)`:

```python
from discord.ext import commands

class GreeterCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = self.bot.get_channel(self.bot.channel_id)
        await channel.send(f"Welcome {member.mention}!")

async def setup(bot, runner, components):
    await bot.add_cog(GreeterCog(bot))
```

Files prefixed with `_` are skipped. If one Cog fails to load, others still load normally.

See [`examples/ebibot/`](examples/ebibot/) for a full real-world example with reminders, Todoist watchdog, auto-upgrade, and docs sync.

**Built-in examples in `examples/ebibot/cogs/`:**

| Cog | Purpose |
|-----|---------|
| `ReminderCog` | Discord-based reminder scheduling |
| `WatchdogCog` | Todoist / external service watchdog |
| `AutoUpgradeCog` | Webhook-triggered package upgrade |
| `DocsSyncCog` | Automated documentation sync on push |
| `AlertResponderCog` | Generic alert monitoring — forwards alerts from monitoring systems to Discord and triggers a Claude Code investigation session |

---

### Minimal Bot (Install as a Package)

If you already have a discord.py bot, add ccdb as a package instead:

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Create a `bot.py`:

```python
import asyncio
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from claude_discord import ClaudeRunner, setup_bridge

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
runner = ClaudeRunner(
    command="claude",
    model="sonnet",
    working_dir="/path/to/your/project",
)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
        allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
    )

asyncio.run(bot.start(os.environ["DISCORD_BOT_TOKEN"]))
```

`setup_bridge()` wires all Cogs automatically. Update to the latest version:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

#### Multi-Channel Setup

To deploy the bot across multiple Discord channels, pass `claude_channel_ids` in addition to (or instead of) `claude_channel_id`:

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),   # primary (fallback for thread creation)
    claude_channel_ids={
        int(os.environ["DISCORD_CHANNEL_ID"]),
        int(os.environ["DISCORD_CHANNEL_ID_2"]),
    },
    allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
)
```

Each channel is fully independent — messages in any of the configured channels spawn a new Claude session thread, and `/skill` commands work across all of them.  `claude_channel_id` is kept for backward compatibility and is used as the fallback thread-creation target when the `/skill` command is invoked outside a configured channel.

#### Mention-Only Channels

To make the bot respond **only when @mentioned** in specific channels (useful for shared channels where you don't want the bot to react to every message):

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_ids={111, 222},
    mention_only_channel_ids={222},  # bot ignores messages in #222 unless @mentioned
    allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
)
```

Or via environment variable (comma-separated channel IDs):

```
MENTION_ONLY_CHANNEL_IDS=222,333
```

Thread replies are not affected — once a session thread is open, all replies are handled normally regardless of mentions.

#### Inline-Reply Channels

To make the bot respond **directly in the channel** (without creating a thread) for specific channels (useful for personal command channels where threads add unnecessary clutter):

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_ids={111, 333},
    inline_reply_channel_ids={333},  # bot replies inline in #333, no thread created
    allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
)
```

Or via environment variable (comma-separated channel IDs):

```
INLINE_REPLY_CHANNEL_IDS=333,444
```

In inline-reply mode, Claude's response is sent directly as a message in the channel rather than spawning a new thread. Sessions are still tracked internally, so follow-up messages in the channel continue the same Claude session.

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | Your Discord bot token | (required) |
| `DISCORD_CHANNEL_ID` | Channel ID for Claude chat | (required) |
| `CLAUDE_COMMAND` | Path to Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Model to use | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Permission mode for CLI | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Skip all permission checks (use with caution) | `false` |
| `CLAUDE_WORKING_DIR` | Working directory for Claude | current dir |
| `MAX_CONCURRENT_SESSIONS` | Max parallel sessions | `3` |
| `SESSION_TIMEOUT_SECONDS` | Session inactivity timeout | `300` |
| `DISCORD_OWNER_ID` | User ID to @-mention when Claude needs input | (optional) |
| `COORDINATION_CHANNEL_ID` | Channel ID used as default fallback for AI Lounge channel | (optional) |
| `MENTION_ONLY_CHANNEL_IDS` | Comma-separated channel IDs where the bot only responds when @mentioned | (optional) |
| `INLINE_REPLY_CHANNEL_IDS` | Comma-separated channel IDs where the bot replies inline (no thread created) | (optional) |
| `CHAT_ONLY_CHANNEL_IDS` | Comma-separated channel IDs in chat-only mode — only Claude's text responses are shown; all technical embeds (tools, thinking, session info, todos) are hidden | (optional) |
| `WORKTREE_BASE_DIR` | Base directory to scan for session worktrees (enables automatic cleanup) | (optional) |
| `CLI_SESSIONS_PATH` | Path to `~/.claude/projects` for CLI session discovery (enables `/sync-sessions`) | (optional) |
| `CUSTOM_COGS_DIR` | Directory containing custom Cog files to load at startup (see [Custom Cogs](#custom-cogs-extend-without-forking)) | (optional) |
| `CLAUDE_ALLOWED_TOOLS` | Comma-separated list of allowed tools for Claude CLI | (optional) |
| `CLAUDE_CHANNEL_IDS` | Additional channel IDs (comma-separated) for multi-channel setup | (optional) |
| `THREAD_INBOX_ENABLED` | Enable the persistent thread inbox (classifies sessions as `waiting`/`done`/`ambiguous` via `claude -p`; shown in thread dashboard) | `false` |
| `THREAD_AUTO_RENAME` | Auto-rename new thread titles using Claude AI — generates a short, descriptive title from the first user message via a background `claude -p` call (never delays session start) | `false` |
| `API_HOST` | REST API bind address | `127.0.0.1` |
| `API_PORT` | REST API port (enables REST API when set) | (optional) |

### Permission Modes — What Works in `-p` Mode

Claude Code CLI runs in **`-p` (non-interactive) mode** when used through ccdb. In this mode, the CLI **cannot prompt for permission** — tools that require approval are immediately rejected. This is a [CLI design constraint](https://code.claude.com/docs/en/headless), not a ccdb limitation.

| Mode | Behavior in `-p` mode | Recommendation |
|------|----------------------|----------------|
| `default` | ❌ **All tools rejected** — unusable | Do not use |
| `acceptEdits` | ⚠️ Edit/Write auto-approved, Bash rejected (Claude falls back to Write for file ops) | Minimum viable option |
| `bypassPermissions` | ✅ All tools approved | Works, but prefer the flag below |
| **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`** | ✅ **All tools approved** | **Recommended** — ccdb already restricts access via `allowed_user_ids` |

**Our recommendation:** Set `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`. Since ccdb controls who can interact with Claude via `allowed_user_ids`, the CLI-level permission checks add friction without meaningful security benefit. The "dangerously" in the name reflects the CLI's general-purpose warning; in the ccdb context where access is already gated, it's the practical choice.

**For fine-grained control**, use `CLAUDE_ALLOWED_TOOLS` to allow specific tools without fully bypassing permissions:

```env
# Example: allow file operations and code execution, but not web access
CLAUDE_ALLOWED_TOOLS=Bash,Read,Write,Edit,Glob,Grep

# Example: read-only mode — Claude can explore but not modify
CLAUDE_ALLOWED_TOOLS=Read,Glob,Grep
```

Common tool names: `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `NotebookEdit`. Set `CLAUDE_PERMISSION_MODE=default` when using this (other modes may override).

**Runtime changes via Discord:** Use `/tools-set` to change allowed tools at runtime without restarting the bot. The setting is persisted and takes effect for all new sessions immediately. Use `/tools-show` to see the current configuration, or `/tools-reset` to revert to the `.env` default.

> **Why don't permission buttons appear in Discord?** The CLI's `-p` mode never emits `permission_request` events, so there's nothing for ccdb to display. The `AskUserQuestion` buttons you see (choice prompts from Claude) are a different mechanism that works correctly. See [#210](https://github.com/ebibibi/claude-code-discord-bridge/issues/210) for the full investigation.

---

## Discord Bot Setup

1. Create a new application at [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a bot and copy the token
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Invite the bot with these permissions:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (for reaction cleanup)
   - Read Message History

---

## GitHub + Claude Code Automation

### Example: Automated Documentation Sync

On every push to `main`, Claude Code:
1. Pulls the latest changes and analyzes the diff
2. Updates English documentation
3. Translates to Japanese (or any target languages)
4. Creates a PR with a bilingual summary
5. Enables auto-merge — merges automatically when CI passes

**GitHub Actions:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Bot configuration:**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="Analyze changes, update docs, create a PR with bilingual summary, enable auto-merge.",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**Security:** Prompts are defined server-side. Webhooks only select which trigger to fire — no arbitrary prompt injection.

### Example: Auto-Approve Owner PRs

```yaml
# .github/workflows/auto-approve.yml
name: Auto Approve Owner PRs
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  auto-approve:
    if: github.event.pull_request.user.login == 'your-username'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: write
    steps:
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: |
          gh pr review "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --approve
          gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --auto --squash
```

---

## Scheduled Tasks

Register periodic Claude Code tasks at runtime — no code changes, no redeploys.

From within a Discord session, Claude can register a task:

```bash
# Claude calls this inside a session:
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Check for outdated deps and open an issue if found", "interval_seconds": 604800}'
```

Or register from your own scripts:

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Weekly security scan", "interval_seconds": 604800}'
```

The 30-second master loop picks up due tasks and spawns Claude Code sessions automatically.

---

## Auto-Upgrade

Automatically upgrade the bot when a new release is published:

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,       # React ✅ in thread, or click button in channel
    slash_command_enabled=True,  # Enable /upgrade slash command (opt-in, default False)
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

#### Manual Trigger via `/upgrade`

When `slash_command_enabled=True`, any authorised user can run `/upgrade` directly in Discord to trigger the same upgrade pipeline — no webhook required. The command works from both text channels and threads (running it inside a thread creates the upgrade thread in the parent channel). It respects `upgrade_approval` and `restart_approval` gates, creates a progress thread, and gracefully handles concurrent runs (replies ephemerally if an upgrade is already in progress).

Before restarting, `AutoUpgradeCog`:

1. **Snapshots active sessions** — Collects all threads with running Claude sessions (duck-typed: any Cog with `_active_runners` dict is discovered automatically).
2. **Drains** — Waits for active sessions to finish naturally.
3. **Marks for resume** — Saves active thread IDs to the pending-resumes table. On next startup, those sessions are resumed with a safety-first prompt: Claude reports what it was working on and asks the user to re-confirm before resuming any implementation work (code changes, commits, PRs). This prevents unintended actions after context compression may have erased task approval state.
4. **Restarts** — Executes the configured restart command.

Any Cog with an `active_count` property is auto-discovered and drained:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

Session marking is fully opt-in — it only activates when `setup_bridge()` has initialized the session database (the default). When enabled, sessions resume with `--resume` continuity so Claude Code can pick up the exact conversation where it left off.

> **Coverage:** `AutoUpgradeCog` covers upgrade-triggered restarts. For *all other* shutdowns (`systemctl stop`, `bot.close()`, SIGTERM), `ClaudeChatCog.cog_unload()` provides a second automatic safety net.

---

## REST API

Optional REST API for notifications and task management. Requires aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/notify` | Send immediate notification |
| POST | `/api/schedule` | Schedule a notification |
| GET | `/api/scheduled` | List pending notifications |
| DELETE | `/api/scheduled/{id}` | Cancel a notification |
| POST | `/api/tasks` | Register a scheduled Claude Code task |
| GET | `/api/tasks` | List registered tasks |
| DELETE | `/api/tasks/{id}` | Remove a task |
| PATCH | `/api/tasks/{id}` | Update a task (enable/disable, change schedule) |
| POST | `/api/spawn` | Create a new Discord thread and start a Claude Code session (non-blocking) |
| POST | `/api/mark-resume` | Mark a thread for automatic resume on next bot startup |
| GET | `/api/lounge` | Read recent AI Lounge messages |
| POST | `/api/lounge` | Post a message to the AI Lounge (with optional `label`) |

```bash
# Send notification (embed format, default)
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "Build succeeded!", "title": "CI/CD"}'

# Send plain text notification (no embed)
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "Deployment done!", "format": "text"}'

# Send a Discord Poll
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Vote now",
    "poll": {
      "question": "Which release track?",
      "answers": ["Stable", "Beta", "Nightly"],
      "duration_hours": 24,
      "allow_multiselect": false
    }
  }'

# Register a recurring task
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Daily standup summary", "interval_seconds": 86400}'
```

---

## Architecture

```
claude_discord/
  main.py                  # Standalone entry point (setup_bridge + custom cog loader)
  cli.py                   # CLI entry point (ccdb setup/start commands)
  setup.py                 # setup_bridge() — one-call Cog wiring
  cog_loader.py            # Dynamic custom Cog loader (CUSTOM_COGS_DIR)
  bot.py                   # Discord Bot class
  protocols.py             # Shared protocols (DrainAware)
  concurrency.py           # Worktree instructions + active session registry
  lounge.py                # AI Lounge prompt builder
  session_sync.py          # CLI session discovery and import
  worktree.py              # WorktreeManager — safe git worktree lifecycle
  cogs/
    claude_chat.py         # Interactive chat (thread creation, message handling)
    skill_command.py       # /skill slash command with autocomplete
    session_manage.py      # /sessions, /sync-sessions, /resume, /resume-info, /sync-settings
    session_sync.py        # Thread-creation and message-posting logic for sync-sessions
    prompt_builder.py      # build_prompt_and_images() — pure function, no Cog/Bot state
    scheduler.py           # Periodic Claude Code task executor
    webhook_trigger.py     # Webhook → Claude Code task execution (CI/CD)
    auto_upgrade.py        # Webhook → package upgrade + drain-aware restart
    event_processor.py     # EventProcessor — state machine for stream-json events
    run_config.py          # RunConfig dataclass — bundles all CLI execution params
    _run_helper.py         # Thin orchestration layer (run_claude_with_config + shim)
  claude/
    runner.py              # Claude CLI subprocess manager
    parser.py              # stream-json event parser
    types.py               # Type definitions for SDK messages
  database/
    models.py              # SQLite schema
    repository.py          # Session CRUD
    task_repo.py           # Scheduled task CRUD
    ask_repo.py            # Pending AskUserQuestion CRUD
    notification_repo.py   # Scheduled notification CRUD
    lounge_repo.py         # AI Lounge message CRUD
    resume_repo.py         # Startup resume CRUD (pending resumes across bot restarts)
    settings_repo.py       # Per-guild settings
    inbox_repo.py          # Thread inbox CRUD (THREAD_INBOX_ENABLED)
  discord_ui/
    status.py              # Emoji reaction manager (debounced)
    chunker.py             # Fence- and table-aware message splitting
    embeds.py              # Discord embed builders
    views.py               # Stop button and shared UI components
    ask_bus.py             # Event bus for AskUserQuestion communication
    ask_view.py            # Buttons/Select Menus for AskUserQuestion
    ask_handler.py         # collect_ask_answers() — AskUserQuestion UI + DB lifecycle
    streaming_manager.py   # StreamingMessageManager — debounced in-place message edits
    tool_timer.py          # LiveToolTimer — elapsed time counter for long-running tools
    thread_dashboard.py    # Live pinned embed showing session states
    plan_view.py           # Approve/Cancel buttons for Plan Mode (ExitPlanMode)
    permission_view.py     # Allow/Deny buttons for tool permission requests
    elicitation_view.py    # Discord UI for MCP elicitation (Modal form or URL button)
    file_sender.py         # File delivery via .ccdb-attachments
    inbox_classifier.py    # classify() — lightweight claude -p call to label sessions
    thread_renamer.py      # suggest_title() — background claude -p call for auto thread naming
  ext/
    api_server.py          # REST API (optional, requires aiohttp)
  utils/
    logger.py              # Logging setup
examples/
  ebibot/                  # Real-world example: personal bot with custom Cogs
    cogs/
      reminder.py          # /remind slash command + scheduled notifications
      watchdog.py          # Todoist overdue task monitor
      auto_upgrade.py      # Self-update via GitHub webhook
      docs_sync.py         # Auto-translate docs on push
```

### Design Philosophy

- **CLI spawn, not API** — Invokes `claude -p --output-format stream-json`, giving full Claude Code features (CLAUDE.md, skills, tools, memory) without reimplementing them. Runs on your Claude Pro/Max subscription — no API key, no per-token billing
- **Concurrency first** — Multiple simultaneous sessions are the expected case, not an edge case; every session gets worktree instructions, the registry and AI Lounge handle the rest
- **Discord as glue** — Discord provides UI, threading, reactions, webhooks, and persistent notifications; no custom frontend needed
- **Framework, not application** — Install as a package, add Cogs to your existing bot, configure via code
- **Zero-code extensibility** — Add scheduled tasks and webhook triggers without touching source
- **Security by simplicity** — ~8000 lines of auditable Python; subprocess exec only, no shell expansion

---

## Testing

```bash
uv run pytest tests/ -v --cov=claude_discord
```

1050+ tests covering parser, chunker, repository, runner, streaming, webhook triggers, auto-upgrade (including `/upgrade` slash command, thread-invocation, and approval button), REST API, AskUserQuestion UI, thread dashboard, scheduled tasks, session sync, AI Lounge, startup resume, model switching, compact detection, TodoWrite progress embeds, custom Cog loader, permission/elicitation/plan-mode event parsing, and thread inbox classification.

---

## How This Project Was Built

**This codebase is developed by [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, Anthropic's AI coding agent, under the direction of [@ebibibi](https://github.com/ebibibi). The human author defines requirements, reviews pull requests, and approves all changes — Claude Code does the implementation.

This means:

- **Implementation is AI-generated** — architecture, code, tests, documentation
- **Human review is applied at the PR level** — every change goes through GitHub pull requests and CI before merging
- **Bug reports and PRs are welcome** — Claude Code will be used to address them
- **This is a real-world example of human-directed, AI-implemented open source software**

The project started on 2026-02-18 and continues to evolve through iterative conversation with Claude Code.

---

## Real-World Example

**[`examples/ebibot/`](examples/ebibot/)** — A personal Discord bot built on this framework, included right in this repo. Demonstrates the custom Cog loader with:

- **ReminderCog** — `/remind HH:MM "message"` slash command + 30-second send loop
- **WatchdogCog** — Todoist overdue task monitor (30-minute check, daily dedup, severity-based alerts)
- **AutoUpgradeCog** — Self-updating via GitHub webhook + systemctl restart
- **DocsSyncCog** — Auto-translate documentation on push via webhook

Run it with: `ccdb start --cogs-dir examples/ebibot/cogs/`

> The EbiBot custom Cogs were previously maintained in a [separate repository](https://github.com/ebibibi/discord-bot). They are now co-located here so Claude Code always has full context of both the framework and the customizations — preventing accidental feature duplication.

---

## Inspired By

- [OpenClaw](https://github.com/openclaw/openclaw) — Emoji status reactions, message debouncing, fence-aware chunking
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI spawn + stream-json approach
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Permission control patterns
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Thread-per-conversation model

---

## License

MIT
