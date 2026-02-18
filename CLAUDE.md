# claude-discord

Discord frontend for Claude Code CLI. **This is a framework (OSS library), not a personal bot.**

## Framework vs Instance

- **claude-discord** (this repo) = reusable OSS framework. No personal config, no secrets, no server-specific logic.
- Personal instances (e.g. EbiBot) install this as a package and import the Cog. The instance repo handles server-specific config, additional Cogs, and secrets.
- When adding features: if it's useful to anyone → add here. If it's personal workflow → add in the instance repo.

## Architecture

- **Python 3.10+** with discord.py v2
- **Cog pattern** for modular features
- **Repository pattern** for data access (SQLite via aiosqlite)
- **asyncio.subprocess** for Claude Code CLI invocation

## Key Design Decisions

1. **CLI spawn, not API**: We invoke `claude -p --output-format stream-json` as a subprocess, not the Anthropic API directly. This gives us all Claude Code features (CLAUDE.md, skills, tools, memory) for free.
2. **Thread = Session**: Each Discord thread maps 1:1 to a Claude Code session ID. Replies in a thread continue the same session via `--resume`.
3. **Emoji reactions for status**: Non-intrusive progress indication on the user's message.
4. **Fence-aware chunking**: Never split Discord messages inside a code block.
5. **Installable package**: `claude_discord` is a proper Python package. Consumers install via `uv add git+...` or `pip install git+...`, not by copying files.
6. **Shared run helper**: `cogs/_run_helper.py` centralizes Claude CLI execution logic used by both ClaudeChatCog and SkillCommandCog.

## Package Management

Uses **uv** for fast dependency management. No venv setup needed.

## Running (standalone)

```bash
cp .env.example .env
# Edit .env with your Discord bot token and channel ID
uv run python -m claude_discord.main
```

## Testing

```bash
uv run pytest tests/ -v --cov=claude_discord
```

## Project Structure

```
claude_discord/          # Installable Python package
  __init__.py            # Public API exports
  main.py                # Standalone entry point
  bot.py                 # Discord Bot class
  cogs/
    claude_chat.py       # Main chat Cog (thread creation, message handling)
    skill_command.py     # /skill slash command with autocomplete
    _run_helper.py       # Shared Claude CLI execution logic (DRY)
  claude/
    runner.py            # Claude CLI subprocess manager
    parser.py            # stream-json event parser
    types.py             # Type definitions for SDK messages
  database/
    models.py            # SQLite schema
    repository.py        # Session CRUD operations
  discord_ui/
    status.py            # Emoji reaction status manager
    chunker.py           # Fence-aware message splitting
    embeds.py            # Discord embed builders
  utils/
    logger.py            # Logging setup
tests/                   # pytest test suite (48 tests)
pyproject.toml           # Package metadata + dependencies
uv.lock                  # Dependency lock file
CONTRIBUTING.md          # Contribution guidelines
```

## Commit Style

```
<type>: <description>
```

Types: feat, fix, refactor, docs, test, chore, security
