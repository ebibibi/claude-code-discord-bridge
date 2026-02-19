# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to Discord and GitHub. A framework that bridges Claude Code CLI with Discord for **interactive chat, CI/CD automation, and GitHub workflow integration**.

Claude Code is great in the terminal — but it can do much more. This bridge lets you **use Claude Code in your GitHub development workflow**: automatically sync documentation, review and merge PRs, and run any Claude Code task triggered by GitHub Actions. All through Discord as the universal glue.

**[日本語](docs/ja/README.md)** | **[简体中文](docs/zh-CN/README.md)** | **[한국어](docs/ko/README.md)** | **[Español](docs/es/README.md)** | **[Português](docs/pt-BR/README.md)** | **[Français](docs/fr/README.md)**

> **Disclaimer:** This project is not affiliated with, endorsed by, or officially connected to Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic, PBC. This is an independent open-source tool that interfaces with the Claude Code CLI.

> **Built entirely by Claude Code.** This project was designed, implemented, tested, and documented by Claude Code itself — the AI coding agent from Anthropic. The human author has not read the source code. See [How This Project Was Built](#how-this-project-was-built) for details.

## Two Ways to Use It

### 1. Interactive Chat (Mobile / Desktop)

Use Claude Code from your phone or any device with Discord. Each conversation becomes a thread with full session persistence.

```
You (Discord)  →  Bridge  →  Claude Code CLI
    ↑                              ↓
    ←──── stream-json output ─────←
```

### 2. CI/CD Automation (GitHub → Discord → Claude Code → GitHub)

Trigger Claude Code tasks from GitHub Actions via Discord webhooks. Claude Code runs autonomously — reading code, updating docs, creating PRs, and enabling auto-merge.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Real-world example:** On every push to main, Claude Code automatically analyzes changes, updates documentation in English and Japanese, creates a PR with a bilingual summary, and enables auto-merge. No human interaction required.

## Features

### Interactive Chat
- **Thread = Session** — Each task gets its own Discord thread, mapped 1:1 to a Claude Code session
- **Real-time status** — Emoji reactions show what Claude is doing (🧠 thinking, 🛠️ reading files, 💻 editing, 🌐 web search)
- **Streaming text** — Intermediate assistant text appears as Claude works, not just at the end
- **Tool result display** — Tool use results shown as embeds in real-time
- **Extended thinking** — Claude's reasoning appears as spoiler-tagged embeds (click to reveal)
- **Session persistence** — Continue conversations across messages via `--resume`
- **Skill execution** — Run Claude Code skills via `/skill` with autocomplete, optional arguments, and in-thread resume
- **Concurrent sessions** — Run multiple sessions in parallel (configurable limit)
- **Stop without clearing** — `/stop` halts a running session while preserving it for resume
- **Attachment support** — Text-type file attachments are automatically appended to the prompt (up to 5 files, 50 KB each)
- **Timeout notifications** — Dedicated embed with elapsed seconds and actionable guidance when a session times out
- **Interactive questions** — When Claude calls `AskUserQuestion`, the bot renders Discord Buttons or a Select Menu and resumes the session with your answer
- **Session status dashboard** — A live pinned embed in the main channel shows which threads are processing vs. waiting for input; owner is @-mentioned when Claude needs a reply

### CI/CD Automation
- **Webhook triggers** — Trigger Claude Code tasks from GitHub Actions or any CI/CD system
- **Auto-upgrade** — Automatically update the bot when upstream packages are released
- **REST API** — Push notifications to Discord from external tools (optional, requires aiohttp)

### Security
- **No shell injection** — `asyncio.create_subprocess_exec` only, never `shell=True`
- **Session ID validation** — Strict regex before passing to `--resume`
- **Flag injection prevention** — `--` separator before all prompts
- **Secret isolation** — Bot token and secrets stripped from subprocess environment
- **User authorization** — `allowed_user_ids` restricts who can invoke Claude

## Skills

Run [Claude Code skills](https://docs.anthropic.com/en/docs/claude-code) directly from Discord via the `/skill` slash command.

```
/skill name:goodmorning                      → runs /goodmorning
/skill name:todoist args:filter "today"      → runs /todoist filter "today"
/skills                                      → lists all available skills
```

**Features:**
- **Autocomplete** — Type to filter; names and descriptions are searchable
- **Arguments** — Pass additional arguments via the `args` parameter
- **In-thread resume** — Use `/skill` inside an existing Claude thread to run the skill within the current session instead of creating a new thread
- **Hot reload** — New skills added to `~/.claude/skills/` are picked up automatically (60s refresh interval, no restart needed)

## Quick Start

### Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- A Discord bot token with Message Content intent enabled
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Run standalone

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edit .env with your bot token and channel ID

uv run python -m claude_discord.main
```

### Install as a package

If you already have a discord.py bot running (Discord allows only one Gateway connection per token):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

# Initialize
await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

# Add to your existing bot
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

Update to the latest version:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

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
| `DISCORD_OWNER_ID` | Discord user ID to @-mention when Claude needs input | (optional) |

## Discord Bot Setup

1. Create a new application at [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a bot and copy the token
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Invite the bot to your server with these permissions:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (for reaction cleanup)
   - Read Message History

## GitHub + Claude Code Automation

The webhook trigger system lets you build fully autonomous CI/CD workflows where Claude Code acts as an intelligent agent — not just running scripts, but understanding code changes and making decisions.

### Example: Automated Documentation Sync

On every push to main, Claude Code:
1. Pulls the latest changes and analyzes the diff
2. Updates English documentation if source code changed
3. Translates to Japanese (or any target languages)
4. Creates a PR with a bilingual summary
5. Enables auto-merge — PR merges automatically when CI passes

**GitHub Actions workflow:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # Skip commits from docs-sync itself (infinite loop prevention)
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
    "🚀 deploy": WebhookTrigger(
        prompt="Deploy to staging environment.",
        timeout=300,
    ),
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**Security:** Only webhook messages are processed. Optional `allowed_webhook_ids` for stricter control. Prompts are defined server-side — webhooks only select which trigger to fire.

### Example: Auto-Approve Owner PRs

Automatically approve and auto-merge your own PRs after CI passes:

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

## Auto-Upgrade

Automatically upgrade the bot when an upstream package is released.

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

**Pipeline:** Upstream push → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → service restart.

### Graceful Drain (DrainAware)

Before restarting, AutoUpgradeCog waits for all active sessions to finish. Any Cog that implements an `active_count` property (satisfying the `DrainAware` protocol) is automatically discovered — no manual `drain_check` lambda needed.

Built-in DrainAware Cogs: `ClaudeChatCog`, `WebhookTriggerCog`.

To make your own Cog drain-aware, just add an `active_count` property:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

You can still pass an explicit `drain_check` callable to override auto-discovery.

### Restart Approval

For self-update scenarios (e.g. updating the bot from within its own Discord session), enable `restart_approval` to prevent automatic restarts:

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

With `restart_approval=True`, after upgrading the package the bot posts a message asking for approval. React with ✅ to trigger the restart. The bot sends periodic reminders until approved.

## REST API

Optional REST API for pushing notifications to Discord from external tools. Requires aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

```python
from claude_discord import NotificationRepository
from claude_discord.ext.api_server import ApiServer

repo = NotificationRepository("data/notifications.db")
await repo.init_db()

api = ApiServer(
    repo=repo,
    bot=bot,
    default_channel_id=YOUR_CHANNEL_ID,
    host="127.0.0.1",
    port=8080,
    api_secret="your-secret-token",  # Optional Bearer auth
)
await api.start()
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/notify` | Send immediate notification |
| POST | `/api/schedule` | Schedule notification for later |
| GET | `/api/scheduled` | List pending notifications |
| DELETE | `/api/scheduled/{id}` | Cancel a scheduled notification |

### Examples

```bash
# Health check
curl http://localhost:8080/api/health

# Send notification
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "Build succeeded!", "title": "CI/CD"}'

# Schedule notification
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "Time to review PRs", "scheduled_at": "2026-01-01T09:00:00"}'
```

## Architecture

```
claude_discord/
  main.py                  # Standalone entry point
  bot.py                   # Discord Bot class
  cogs/
    claude_chat.py         # Interactive chat (thread creation, message handling)
    skill_command.py       # /skill slash command with autocomplete
    webhook_trigger.py     # Webhook → Claude Code task execution (CI/CD)
    auto_upgrade.py        # Webhook → package upgrade + restart
    _run_helper.py         # Shared Claude CLI execution logic
  claude/
    runner.py              # Claude CLI subprocess manager
    parser.py              # stream-json event parser
    types.py               # Type definitions for SDK messages
  database/
    models.py              # SQLite schema
    repository.py          # Session CRUD operations
    notification_repo.py   # Scheduled notification CRUD
  discord_ui/
    status.py              # Emoji reaction status manager (debounced)
    chunker.py             # Fence- and table-aware message splitting
    embeds.py              # Discord embed builders
    ask_view.py            # Discord Buttons/Select Menus for AskUserQuestion
    thread_dashboard.py    # Live pinned embed showing session states per thread
  ext/
    api_server.py          # REST API server (optional, requires aiohttp)
  utils/
    logger.py              # Logging setup
```

### Design Philosophy

- **CLI spawn, not API** — We invoke `claude -p --output-format stream-json`, giving us full Claude Code features (CLAUDE.md, skills, tools, memory) for free
- **Discord as glue** — Discord provides the UI, threading, notifications, and webhook infrastructure
- **Framework, not application** — Install as a package, add Cogs to your existing bot, configure via code
- **Security by simplicity** — ~2500 lines of auditable Python, no shell execution, no arbitrary code paths

## Testing

```bash
uv run pytest tests/ -v --cov=claude_discord
```

400+ tests covering parser, chunker, repository, runner, streaming, webhook triggers, auto-upgrade, REST API, AskUserQuestion UI, and thread status dashboard.

## How This Project Was Built

**This entire codebase was written by [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, Anthropic's AI coding agent. The human author ([@ebibibi](https://github.com/ebibibi)) provided requirements and direction via natural language, but has not manually read or edited the source code.

This means:

- **All code was AI-generated** — architecture, implementation, tests, documentation
- **The human author cannot guarantee correctness at the code level** — review the source if you need assurance
- **Bug reports and PRs are welcome** — Claude Code will likely be used to address them too
- **This is a real-world example of AI-authored open source software** — use it as a reference for what Claude Code can build

The project started on 2026-02-18 and continues to evolve through iterative conversation with Claude Code.

## Real-World Example

**[EbiBot](https://github.com/ebibibi/discord-bot)** — A personal Discord bot that uses claude-code-discord-bridge as a package dependency. Includes automated documentation sync (English + Japanese), push notifications, Todoist watchdog, and CI/CD integration with GitHub Actions. See it as a reference for how to build your own bot on top of this framework.

## Inspired By

- [OpenClaw](https://github.com/openclaw/openclaw) — Emoji status reactions, message debouncing, fence-aware chunking
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI spawn + stream-json approach
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Permission control patterns
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Thread-per-conversation model

## License

MIT
