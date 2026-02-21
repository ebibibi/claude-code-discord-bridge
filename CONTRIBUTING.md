# Contributing to claude-code-discord-bridge

Thanks for your interest in contributing! This project was built by Claude Code and welcomes contributions from both humans and AI agents.

## Branch Workflow

We use **GitHub Flow** — a simple, PR-based workflow:

```
main (always releasable)
  ├── feature/add-xxx   → PR → CI passes → review → merge
  ├── fix/issue-123     → PR → CI passes → review → merge
  └── (direct push to main is not allowed)
```

### Steps

1. **Fork** the repo (or create a branch if you have write access)
2. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** — write code, add tests
4. **Push** your branch and **open a PR** against `main`
5. **CI runs automatically** — tests + lint on Python 3.10/3.11/3.12
6. Once CI passes and the PR is reviewed, it gets **merged to main**

### Branch Naming

- `feature/description` — New functionality
- `fix/description` or `fix/issue-123` — Bug fixes
- `docs/description` — Documentation only
- `refactor/description` — Code restructuring without behavior change

## Development Setup

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
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
uv run ruff check claude_discord/
uv run ruff format claude_discord/
```

## Project Structure

- `claude_discord/claude/` — Claude Code CLI interaction (runner, parser, types)
- `claude_discord/cogs/` — Discord.py Cogs (chat, skill command, webhook trigger, auto-upgrade)
- `claude_discord/database/` — SQLite session and notification persistence
- `claude_discord/discord_ui/` — Discord UI components (status, chunker, embeds)
- `claude_discord/ext/` — Optional extensions (REST API server — requires aiohttp)
- `tests/` — pytest test suite

## Submitting Changes

1. Fork the repo and create a feature branch
2. Write tests for new functionality
3. Run locally before pushing:
   ```bash
   uv run ruff check claude_discord/
   uv run ruff format --check claude_discord/
   uv run pytest tests/ -v
   ```
4. Submit a PR with a clear description of what and why
5. CI will run automatically — all checks must pass

## Adding a New Cog

1. Create `claude_discord/cogs/your_cog.py`
2. Use `_run_helper.run_claude_with_config(RunConfig(...))` for Claude CLI execution
   (The legacy `run_claude_in_thread()` shim is still available but prefer `run_claude_with_config`)
3. Export from `claude_discord/cogs/__init__.py`
4. Add to `claude_discord/__init__.py` public API
5. Write tests in `tests/test_your_cog.py`

## A Note on AI-Generated Code

This project was written by Claude Code. If you use Claude Code or other AI tools to contribute, that's perfectly fine — just make sure the code works, is tested, and makes sense.
