# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Use [Claude Code](https://docs.anthropic.com/en/docs/claude-code) from your phone. A thin Discord frontend that gives you **full Claude Code CLI access** through Discord threads — designed for mobile development when you're away from your terminal.

**[日本語](docs/ja/README.md)** | **[简体中文](docs/zh-CN/README.md)** | **[한국어](docs/ko/README.md)** | **[Español](docs/es/README.md)** | **[Português](docs/pt-BR/README.md)** | **[Français](docs/fr/README.md)**

> **Disclaimer:** This project is not affiliated with, endorsed by, or officially connected to Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic, PBC. This is an independent open-source tool that interfaces with the Claude Code CLI.

> **Built entirely by Claude Code.** This project was designed, implemented, tested, and documented by Claude Code itself — the AI coding agent from Anthropic. The human author has not read the source code. See [How This Project Was Built](#how-this-project-was-built) for details.

## Why This Exists

I run 3-4 projects in parallel with Claude Code. On my phone via [Termux](https://termux.dev/) + tmux, managing multiple terminal sessions became painful — which tmux window was which project? What was I doing in each one? The context-switching overhead killed my productivity.

**Discord solves this perfectly:**

- Each project conversation is a **named thread** — instantly scannable
- Threads preserve full history — come back hours later and pick up where you left off
- Emoji reactions show status at a glance — no need to scroll through terminal output
- Discord is free, works on every phone, and handles notifications natively

## What This Is (and Isn't)

**This is:** A focused bridge between Discord and Claude Code CLI. It spawns `claude -p --output-format stream-json` as a subprocess, parses the output, and posts it back to Discord. That's it.

**This is not:** A feature-rich Discord bot, an AI chatbot framework, or a replacement for the Claude Code terminal experience. There's no custom AI logic, no plugin system, no admin dashboard.

**Your Claude Code environment does the heavy lifting.** Your CLAUDE.md, skills, tools, memory, MCP servers — they all work exactly as they do in the terminal. This bridge just provides the UI layer.

**Security model:** Run it on your own private Discord server, in a channel only you can access. The bot is intentionally simple — fewer features means fewer attack surfaces. You built it yourself, you can read every line of code, and there's nothing phoning home.

## How It Compares

| | claude-code-discord-bridge | [OpenClaw](https://github.com/openclaw/openclaw) & similar |
|---|---|---|
| **Focus** | Mobile-first Claude Code access | Full-featured Discord AI bot |
| **AI backend** | Claude Code CLI (subprocess) | Direct API calls |
| **Features** | Minimal: threads, status, chunking | Extensive: plugins, admin, multi-model |
| **Configuration** | Your existing Claude Code setup | Bot-specific config |
| **Skills/tools** | Inherited from Claude Code | Defined in bot config |
| **Target user** | Developer who already uses Claude Code | Anyone wanting an AI Discord bot |
| **Complexity** | ~800 lines of Python | Thousands of lines |

**If you want a Discord AI chatbot**, use OpenClaw or similar projects — they're far more capable.

**If you want to use Claude Code from your phone**, with all your existing project context, skills, and tools — that's what this is for.

## Features

- **Thread = Session** — Each task gets its own Discord thread, mapped 1:1 to a Claude Code session
- **Real-time status** — Emoji reactions show what Claude is doing (🧠 thinking, 🛠️ reading files, 💻 editing, 🌐 web search)
- **Streaming text** — Intermediate assistant text appears as Claude works, not just at the end
- **Tool result display** — Tool use embeds update in place to show what each tool returned
- **Extended thinking** — Claude's reasoning appears as spoiler-tagged embeds (click to reveal)
- **Session persistence** — Continue conversations across messages via `--resume`
- **Skill execution** — Run Claude Code skills (`/skill goodmorning`) via slash commands with autocomplete
- **Fence-aware splitting** — Long responses split at natural boundaries, never breaking code blocks
- **Concurrent sessions** — Run multiple sessions in parallel (configurable limit)
- **Security hardened** — No shell injection, secrets stripped from subprocess env, user authorization

## How It Works

```
You (Discord)  →  Bridge  →  Claude Code CLI
    ↑                                      ↓
    ←──────── stream-json output ──────────←
```

1. Send a message in the configured Discord channel
2. The bot creates a thread and starts a Claude Code session
3. Stream-json output is parsed in real-time for status updates
4. Claude's response is posted back to the thread
5. Reply in the thread to continue the conversation

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

## Architecture

```
claude_discord/
  main.py                  # Standalone entry point
  bot.py                   # Discord Bot class
  cogs/
    claude_chat.py         # Main chat Cog (thread creation, message handling)
    skill_command.py       # /skill slash command with autocomplete
    _run_helper.py         # Shared Claude CLI execution logic
  claude/
    runner.py              # Claude CLI subprocess manager
    parser.py              # stream-json event parser
    types.py               # Type definitions for SDK messages
  database/
    models.py              # SQLite schema
    repository.py          # Session CRUD operations
  discord_ui/
    status.py              # Emoji reaction status manager (debounced)
    chunker.py             # Fence-aware message splitting
    embeds.py              # Discord embed builders
  utils/
    logger.py              # Logging setup
```

### Design Philosophy

- **No custom AI logic** — Claude Code handles all reasoning, tool use, and context
- **No memory system** — Claude Code's built-in sessions + CLAUDE.md handle memory
- **No tool definitions** — Claude Code has its own comprehensive tool set
- **No plugin system** — Add capabilities by configuring Claude Code, not this bot
- **Framework's job is purely UI** — Accept messages, show status, deliver responses

### Security

- `asyncio.create_subprocess_exec` (not shell) prevents command injection
- Session IDs validated with strict regex before use
- `--` separator prevents prompt injection via flag interpretation
- Bot token and secrets stripped from the subprocess environment
- `allowed_user_ids` restricts who can invoke Claude
- Simple codebase (~800 LOC) — easy to audit yourself

## Testing

```bash
uv run pytest tests/ -v --cov=claude_discord
```

71 tests covering parser, chunker, repository, runner, streaming, and run-helper logic.

## How This Project Was Built

**This entire codebase was written by [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, Anthropic's AI coding agent. The human author ([@ebibibi](https://github.com/ebibibi)) provided requirements and direction via natural language, but has not manually read or edited the source code.

This means:

- **All code was AI-generated** — architecture, implementation, tests, documentation
- **The human author cannot guarantee correctness at the code level** — review the source if you need assurance
- **Bug reports and PRs are welcome** — Claude Code will likely be used to address them too
- **This is a real-world example of AI-authored open source software** — use it as a reference for what Claude Code can build

The project was built in a single day (2026-02-18) through iterative conversation with Claude Code, starting from requirements and ending with a working, tested, documented package.

## Real-World Example

**[EbiBot](https://github.com/ebibibi/discord-bot)** — A personal Discord bot that uses claude-code-discord-bridge as a package dependency. Includes custom Cogs for push notifications, Todoist watchdog, and automated documentation sync. See it as a reference for how to build your own bot on top of this framework.

## Inspired By

- [OpenClaw](https://github.com/openclaw/openclaw) — Emoji status reactions, message debouncing, fence-aware chunking
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI spawn + stream-json approach
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Permission control patterns
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Thread-per-conversation model

## License

MIT
