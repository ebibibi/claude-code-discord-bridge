# claude-discord

A Discord frontend for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI. Chat with Claude Code through Discord threads — see real-time status updates, tool usage, and manage sessions from your phone.

> **Built entirely by Claude Code.** This project was designed, implemented, tested, and documented by Claude Code itself — the AI coding agent from Anthropic. The human author has not read the source code. See [How This Project Was Built](#how-this-project-was-built) for details.

## Features

- **Thread-based conversations** — Each task gets its own Discord thread, mapped 1:1 to a Claude Code session
- **Real-time status** — Emoji reactions show what Claude is doing (🧠 thinking, 🛠️ reading files, 💻 editing, 🌐 web search)
- **Session persistence** — Continue conversations across messages using Claude Code's built-in session management
- **Skill execution** — Run Claude Code skills (`/skill goodmorning`) via Discord slash commands with autocomplete
- **Fence-aware splitting** — Long responses are split at natural boundaries, never breaking code blocks
- **Concurrent sessions** — Run multiple Claude Code sessions in parallel (configurable limit)
- **Security hardened** — No shell injection, secrets stripped from subprocess env, user authorization support

## How It Works

```
You (Discord)  →  claude-discord  →  Claude Code CLI
    ↑                                      ↓
    ←──────── stream-json output ──────────←
```

1. Send a message in the configured Discord channel
2. The bot creates a thread and starts a Claude Code session
3. Stream-json output is parsed in real-time for status updates
4. Claude's response is posted back to the thread
5. Reply in the thread to continue the conversation

**Key design decision**: We spawn `claude -p --output-format stream-json` as a subprocess, not the Anthropic API directly. This gives you all Claude Code features for free — CLAUDE.md project context, skills, tools, memory, and MCP servers.

## Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- A Discord bot token with Message Content intent enabled
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick Start

```bash
git clone https://github.com/ebibibi/claude-discord.git
cd claude-discord

cp .env.example .env
# Edit .env with your bot token and channel ID

uv run python -m claude_discord.main
```

## Installation

### Standalone

Run as its own bot process:

```bash
uv run python -m claude_discord.main
```

### Package install (recommended)

Install into your existing discord.py bot and import the Cog. This is the recommended approach if you already have a bot running, since Discord allows only one Gateway connection per token:

```bash
uv add git+https://github.com/ebibibi/claude-discord.git
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
uv lock --upgrade-package claude-discord && uv sync
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

This project is a **framework** (installable Python package) — not a ready-made bot for a specific server.

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

- **No custom AI logic** — Claude Code handles all reasoning, tool use, and context management
- **No memory system** — Claude Code's built-in session management + CLAUDE.md handle memory
- **No tool definitions** — Claude Code has its own comprehensive tool set
- **Framework's job is purely UI** — Accept messages, show status, deliver responses

### Security

- `asyncio.create_subprocess_exec` (not shell) prevents command injection
- Session IDs are validated with a strict regex before use
- `--` separator prevents prompts starting with `-` from being interpreted as flags
- Discord bot token and other secrets are stripped from the subprocess environment
- `allowed_user_ids` parameter restricts who can invoke Claude

## Testing

```bash
uv run pytest tests/ -v --cov=claude_discord
```

48 tests covering parser, chunker, repository, and runner logic.

## How This Project Was Built

**This entire codebase was written by [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, Anthropic's AI coding agent. The human author ([@ebibibi](https://github.com/ebibibi)) provided requirements and direction via natural language, but has not manually read or edited the source code.

This means:

- **All code was AI-generated** — architecture, implementation, tests, documentation
- **The human author cannot guarantee correctness at the code level** — review the source if you need assurance
- **Bug reports and PRs are welcome** — Claude Code will likely be used to address them too
- **This is a real-world example of AI-authored open source software** — use it as a reference for what Claude Code can build

The project was built in a single day (2026-02-18) through iterative conversation with Claude Code, starting from requirements and ending with a working, tested, documented package.

## Inspired By

- [OpenClaw](https://github.com/openclaw/openclaw) — Emoji status reactions, message debouncing, fence-aware chunking
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI spawn + stream-json approach
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Permission control patterns
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Thread-per-conversation model

## License

MIT
