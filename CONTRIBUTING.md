# Contributing to claude-discord

Thanks for your interest in contributing! This project was built by Claude Code and welcomes contributions from both humans and AI agents.

## Development Setup

```bash
git clone https://github.com/ebibibi/claude-discord.git
cd claude-discord
uv sync --dev
```

## Running Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

All tests must pass before submitting a PR.

## Code Style

- **Formatter**: `ruff format`
- **Linter**: `ruff check`
- **Type hints**: Required on all function signatures
- **Python**: 3.10+ (use `from __future__ import annotations` for modern syntax)

```bash
uv run ruff check .
uv run ruff format .
```

## Project Structure

- `claude_discord/claude/` — Claude Code CLI interaction (runner, parser, types)
- `claude_discord/cogs/` — Discord.py Cogs (chat, skill command)
- `claude_discord/database/` — SQLite session persistence
- `claude_discord/discord_ui/` — Discord UI components (status, chunker, embeds)
- `tests/` — pytest test suite

## Submitting Changes

1. Fork the repo and create a feature branch
2. Write tests for new functionality
3. Ensure all tests pass: `uv run pytest tests/ -v`
4. Ensure code passes linting: `uv run ruff check .`
5. Submit a PR with a clear description of what and why

## Adding a New Cog

1. Create `claude_discord/cogs/your_cog.py`
2. Use `_run_helper.run_claude_in_thread()` for Claude CLI execution
3. Export from `claude_discord/cogs/__init__.py`
4. Add to `claude_discord/__init__.py` public API
5. Write tests in `tests/test_your_cog.py`

## A Note on AI-Generated Code

This project was written by Claude Code. If you use Claude Code or other AI tools to contribute, that's perfectly fine — just make sure the code works, is tested, and makes sense.
