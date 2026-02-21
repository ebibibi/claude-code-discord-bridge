# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Run multiple Claude Code sessions in parallel — safely — through Discord.**

Each Discord thread becomes an isolated Claude Code session. Spin up as many as you need: work on a feature in one thread, review a PR in another, run a scheduled task in a third. The bridge handles coordination automatically so concurrent sessions don't clobber each other.

**[日本語](docs/ja/README.md)** | **[简体中文](docs/zh-CN/README.md)** | **[한국어](docs/ko/README.md)** | **[Español](docs/es/README.md)** | **[Português](docs/pt-BR/README.md)** | **[Français](docs/fr/README.md)**

> **Disclaimer:** This project is not affiliated with, endorsed by, or officially connected to Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic, PBC. This is an independent open-source tool that interfaces with the Claude Code CLI.

> **Built entirely by Claude Code.** This entire codebase — architecture, implementation, tests, documentation — was written by Claude Code itself. The human author provided requirements and direction via natural language. See [How This Project Was Built](#how-this-project-was-built).

---

## The Big Idea: Parallel Sessions Without Fear

When you send tasks to Claude Code in separate Discord threads, the bridge does three things automatically:

1. **Concurrency notice injection** — Every session's system prompt includes mandatory instructions: create a git worktree, work only inside it, never touch the main working directory directly.

2. **Active session registry** — Each running session knows about the others. If two sessions are about to touch the same repo, they can coordinate rather than conflict.

3. **Coordination channel** — A shared Discord channel where sessions broadcast start/end events. Both Claude and humans can see at a glance what's happening across all active threads.

```
Thread A (feature)   ──→  Claude Code (worktree-A)
Thread B (PR review) ──→  Claude Code (worktree-B)
Thread C (docs)      ──→  Claude Code (worktree-C)
           ↓ lifecycle events
   #coordination channel
   "A: started on auth refactor"
   "B: reviewing PR #42"
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
- **Multiple contributors**: Different team members each get their own thread; sessions stay aware of each other via the coordination channel.
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

---

## Features

### Interactive Chat
- **Thread = Session** — 1:1 mapping between Discord thread and Claude Code session
- **Real-time status** — Emoji reactions: 🧠 thinking, 🛠️ reading files, 💻 editing, 🌐 web search
- **Streaming text** — Intermediate assistant text appears as Claude works
- **Tool result embeds** — Live tool call results with elapsed time ticking up every 10s
- **Extended thinking** — Reasoning shown as spoiler-tagged embeds (click to reveal)
- **Session persistence** — Resume conversations across messages via `--resume`
- **Skill execution** — `/skill` command with autocomplete, optional args, in-thread resume
- **Hot reload** — New skills added to `~/.claude/skills/` are picked up automatically (60s refresh, no restart)
- **Concurrent sessions** — Multiple parallel sessions with configurable limit
- **Stop without clearing** — `/stop` halts a session while preserving it for resume
- **Attachment support** — Text files auto-appended to prompt (up to 5 × 50 KB)
- **Timeout notifications** — Embed with elapsed time and resume guidance on timeout
- **Interactive questions** — `AskUserQuestion` renders as Discord Buttons or Select Menu; session resumes with your answer; buttons survive bot restarts
- **Thread dashboard** — Live pinned embed showing which threads are active vs. waiting; owner @-mentioned when input is needed
- **Token usage** — Cache hit rate and token counts shown in session-complete embed

### Concurrency & Coordination
- **Worktree instructions auto-injected** — Every session prompted to use `git worktree` before touching any file
- **Active session registry** — In-memory registry; each session sees what the others are doing
- **Coordination channel** — Optional shared channel for cross-session lifecycle broadcasts
- **Coordination scripts** — Claude can call `coord_post.py` / `coord_read.py` from within a session to post and read events

### Scheduled Tasks
- **SchedulerCog** — SQLite-backed periodic task executor with a 30-second master loop
- **Self-registration** — Claude registers tasks via `POST /api/tasks` during a chat session
- **No code changes** — Add, remove, or modify tasks at runtime
- **Enable/disable** — Pause tasks without deleting them (`PATCH /api/tasks/{id}`)

### CI/CD Automation
- **Webhook triggers** — Trigger Claude Code tasks from GitHub Actions or any CI/CD system
- **Auto-upgrade** — Automatically update the bot when upstream packages are released
- **DrainAware restart** — Waits for active sessions to finish before restarting
- **Restart approval** — Optional gate to confirm upgrades before applying

### Session Management
- **Session sync** — Import CLI sessions as Discord threads (`/sync-sessions`)
- **Session list** — `/sessions` with filtering by origin (Discord / CLI / all) and time window
- **Resume info** — `/resume-info` shows the CLI command to continue the current session in a terminal

### Security
- **No shell injection** — `asyncio.create_subprocess_exec` only, never `shell=True`
- **Session ID validation** — Strict regex before passing to `--resume`
- **Flag injection prevention** — `--` separator before all prompts
- **Secret isolation** — Bot token stripped from subprocess environment
- **User authorization** — `allowed_user_ids` restricts who can invoke Claude

---

## Quick Start

### Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- A Discord bot token with Message Content intent enabled
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Standalone

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edit .env with your bot token and channel ID

uv run python -m claude_discord.main
```

### Install as a package

If you already have a discord.py bot (Discord allows only one Gateway connection per token):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from discord.ext import commands
from claude_discord import ClaudeRunner, setup_bridge

bot = commands.Bot(...)
runner = ClaudeRunner(command="claude", model="sonnet")

@bot.event
async def on_ready():
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=YOUR_CHANNEL_ID,
        allowed_user_ids={YOUR_USER_ID},
    )
```

`setup_bridge()` wires all Cogs automatically. New Cogs added to ccdb are included with no consumer code changes.

Update to the latest version:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | Your Discord bot token | (required) |
| `DISCORD_CHANNEL_ID` | Channel ID for Claude chat | (required) |
| `CLAUDE_COMMAND` | Path to Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Model to use | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Permission mode for CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Working directory for Claude | current dir |
| `MAX_CONCURRENT_SESSIONS` | Max parallel sessions | `3` |
| `SESSION_TIMEOUT_SECONDS` | Session inactivity timeout | `300` |
| `DISCORD_OWNER_ID` | User ID to @-mention when Claude needs input | (optional) |
| `COORDINATION_CHANNEL_ID` | Channel ID for cross-session event broadcasts | (optional) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Auto-create coordination channel by name | (optional) |

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
    restart_approval=True,  # React with ✅ to confirm restart
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

Before restarting, `AutoUpgradeCog` waits for all active sessions to finish. Any Cog with an `active_count` property is auto-discovered and drained:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

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

```bash
# Send notification
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "Build succeeded!", "title": "CI/CD"}'

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
  main.py                  # Standalone entry point
  setup.py                 # setup_bridge() — one-call Cog wiring
  bot.py                   # Discord Bot class
  concurrency.py           # Worktree instructions + active session registry
  cogs/
    claude_chat.py         # Interactive chat (thread creation, message handling)
    skill_command.py       # /skill slash command with autocomplete
    session_manage.py      # /sessions, /sync-sessions, /resume-info
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
  coordination/
    service.py             # Posts session lifecycle events to shared channel
  database/
    models.py              # SQLite schema
    repository.py          # Session CRUD
    task_repo.py           # Scheduled task CRUD
    ask_repo.py            # Pending AskUserQuestion CRUD
    notification_repo.py   # Scheduled notification CRUD
    settings_repo.py       # Per-guild settings
  discord_ui/
    status.py              # Emoji reaction manager (debounced)
    chunker.py             # Fence- and table-aware message splitting
    embeds.py              # Discord embed builders
    ask_view.py            # Buttons/Select Menus for AskUserQuestion
    ask_handler.py         # collect_ask_answers() — AskUserQuestion UI + DB lifecycle
    streaming_manager.py   # StreamingMessageManager — debounced in-place message edits
    tool_timer.py          # LiveToolTimer — elapsed time counter for long-running tools
    thread_dashboard.py    # Live pinned embed showing session states
  session_sync.py          # CLI session discovery and import
  ext/
    api_server.py          # REST API (optional, requires aiohttp)
  utils/
    logger.py              # Logging setup
```

### Design Philosophy

- **CLI spawn, not API** — Invokes `claude -p --output-format stream-json`, giving full Claude Code features (CLAUDE.md, skills, tools, memory) without reimplementing them
- **Concurrency first** — Multiple simultaneous sessions are the expected case, not an edge case; every session gets worktree instructions, the registry and coordination channel handle the rest
- **Discord as glue** — Discord provides UI, threading, reactions, webhooks, and persistent notifications; no custom frontend needed
- **Framework, not application** — Install as a package, add Cogs to your existing bot, configure via code
- **Zero-code extensibility** — Add scheduled tasks and webhook triggers without touching source
- **Security by simplicity** — ~3000 lines of auditable Python; subprocess exec only, no shell expansion

---

## Testing

```bash
uv run pytest tests/ -v --cov=claude_discord
```

470+ tests covering parser, chunker, repository, runner, streaming, webhook triggers, auto-upgrade, REST API, AskUserQuestion UI, thread dashboard, scheduled tasks, and session sync.

---

## How This Project Was Built

**This entire codebase was written by [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, Anthropic's AI coding agent. The human author ([@ebibibi](https://github.com/ebibibi)) provided requirements and direction via natural language, but has not manually read or edited the source code.

This means:

- **All code was AI-generated** — architecture, implementation, tests, documentation
- **The human author cannot guarantee correctness at the code level** — review the source if you need assurance
- **Bug reports and PRs are welcome** — Claude Code will be used to address them
- **This is a real-world example of AI-authored open source software**

The project started on 2026-02-18 and continues to evolve through iterative conversation with Claude Code.

---

## Real-World Example

**[EbiBot](https://github.com/ebibibi/discord-bot)** — A personal Discord bot built on this framework. Includes automated documentation sync (English + Japanese), push notifications, Todoist watchdog, scheduled health checks, and GitHub Actions CI/CD. Use it as a reference for building your own bot.

---

## Inspired By

- [OpenClaw](https://github.com/openclaw/openclaw) — Emoji status reactions, message debouncing, fence-aware chunking
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI spawn + stream-json approach
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Permission control patterns
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Thread-per-conversation model

---

## License

MIT
