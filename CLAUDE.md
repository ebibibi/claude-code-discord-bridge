# claude-code-discord-bridge (ccdb)

Discord frontend for Claude Code CLI. **This is a framework (OSS library), not a personal bot.**

**略称: ccdb** (claude-code-discord-bridge)

## Framework vs Instance

- **claude-code-discord-bridge** (this repo) = reusable OSS framework. No personal config, no secrets, no server-specific logic.
- Personal instances (e.g. EbiBot) install this as a package and import the Cog. The instance repo handles server-specific config, additional Cogs, and secrets.
- When adding features: if it's useful to anyone → add here. If it's personal workflow → add in the instance repo.

### Zero-Config Principle (Critical)

**Consumers must get new features by updating the package alone — no code changes required.**

- New features should be enabled by default (auto-discovery, sensible defaults)
- New constructor parameters must have backward-compatible defaults (`= None`)
- If a feature requires consumers to wire something up, the design is wrong — fix it in ccdb
- Consumers should NEVER need to copy, wrap, or subclass ccdb Cogs. If they do, ccdb is missing an extension point

## Architecture

- **Python 3.10+** with discord.py v2
- **Cog pattern** for modular features
- **Repository pattern** for data access (SQLite via aiosqlite)
- **asyncio.subprocess** for Claude Code CLI invocation (never shell=True)

## Key Design Decisions

1. **CLI spawn, not API**: We invoke `claude -p --output-format stream-json` as a subprocess, not the Anthropic API directly. This gives us all Claude Code features (CLAUDE.md, skills, tools, memory) for free.
2. **Thread = Session**: Each Discord thread maps 1:1 to a Claude Code session ID. Replies in a thread continue the same session via `--resume`.
3. **Emoji reactions for status**: Non-intrusive progress indication on the user's message. Debounced to avoid Discord rate limits.
4. **Fence-aware chunking**: Never split Discord messages inside a code block.
5. **Installable package**: `claude_discord` is a proper Python package. Consumers install via `uv add git+...` or `pip install git+...`, not by copying files.
6. **Shared run helper**: `cogs/_run_helper.py` centralizes Claude CLI execution logic used by both ClaudeChatCog and SkillCommandCog.
7. **REST API as the control plane**: Claude Code subprocesses communicate back to ccdb via REST API (`CCDB_API_URL` env var), not via stdout markers or special output formats. This makes the interface explicit, testable, and usable by external systems (GitHub Actions, etc.). See `ext/api_server.py`.
8. **SQLite-backed dynamic scheduler**: Scheduled tasks are stored in `scheduled_tasks` DB table and executed by a single `discord.ext.tasks` master loop (every 30s). Tasks are registered at runtime via REST API — no code changes needed to add new tasks. `discord.ext.tasks` decorators are only used for the master loop, not per-task (they're static/compile-time constructs).
9. **Claude handles "what", ccdb handles "when"**: For scheduled tasks, ccdb only manages the schedule. All domain logic (what to check, how to deduplicate, what to post) lives in the Claude prompt. No GitHub/AzureDevOps-specific code in ccdb itself.

### Why REST API over stdout markers for Claude→ccdb communication

Alternative considered: Claude embeds `<!-- ccdb:schedule {...} -->` in response text; ccdb parses stdout.

**Rejected because**: fragile text parsing, untestable, can't be triggered externally, implicit side effect from output.

**REST API chosen because**: clean interface, independently testable, usable by external systems, already an established ccdb pattern (`ext/api_server.py`). Claude uses its Bash tool to `curl $CCDB_API_URL/api/tasks`.

## Development

### Setup

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv sync --dev
```

### Running Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

All tests must pass before submitting a PR. CI runs on Python 3.10, 3.11, and 3.12.

### Linting & Formatting

```bash
uv run ruff check claude_discord/    # lint
uv run ruff format claude_discord/   # format
```

CI enforces both `ruff check` and `ruff format --check`. Fix all issues before pushing.

### Running (standalone)

```bash
cp .env.example .env
# Edit .env with your Discord bot token and channel ID
uv run python -m claude_discord.main
```

## Code Conventions

### Style

- **Formatter/Linter**: ruff (config in `pyproject.toml`)
- **Type hints**: Required on all function signatures
- **Python**: 3.10+ — use `from __future__ import annotations` in every file
- **Line length**: 100 characters max
- **Imports**: Sorted by ruff (`I` rule). Use `TYPE_CHECKING` for type-only imports

### Error Handling

- Use `contextlib.suppress(discord.HTTPException)` for Discord API calls that may fail (reactions, message edits)
- Never silently swallow errors in business logic — log them
- CLI subprocess errors should yield a `StreamEvent` with `error` field, not raise exceptions

### Security (Critical — Auto-Enforced)

This project runs arbitrary Claude Code sessions. Security is non-negotiable.

**Before every commit**, run the security audit (see `.claude/skills/security-audit/SKILL.md`):

- **Always `create_subprocess_exec`**: Never use `shell=True`. The prompt is a direct argument, not shell-interpolated.
- **`--` separator**: Always use `--` before the prompt argument to prevent flag injection
- **Session ID validation**: Strict regex `^[a-f0-9\-]+$` before passing to `--resume`
- **Skill name validation**: Strict regex `^[\w-]+$` before passing to Claude
- **Environment stripping**: `DISCORD_BOT_TOKEN` and other secrets are removed from the subprocess env so Claude's Bash tool can't read them
- **No `dangerously_skip_permissions` by default**: This flag exists for advanced users who understand the risk

If you modify `runner.py`, `_run_helper.py`, or any Cog, the security audit is **mandatory** before committing.

### Naming

- Files: `snake_case.py`
- Classes: `PascalCase` (e.g., `ClaudeRunner`, `StatusManager`)
- Functions/methods: `snake_case`
- Private: prefix with `_` (e.g., `_build_args`, `_run_helper.py`)
- Constants: `UPPER_SNAKE_CASE`

### Testing (TDD Enforced)

**All new features and bug fixes MUST follow TDD: write tests FIRST, then implement.**

1. **RED**: Write a failing test → `uv run pytest tests/test_xxx.py -v` → confirm it FAILS
2. **GREEN**: Write minimal code to pass → confirm it PASSES
3. **REFACTOR**: Clean up, keeping tests green
4. **VERIFY**: `uv run ruff check claude_discord/ && uv run pytest tests/ -v --cov=claude_discord`

See `.claude/skills/tdd/SKILL.md` for detailed patterns per module type.

- Use `pytest` with `pytest-asyncio` (auto mode)
- Test files go in `tests/` mirroring the source structure
- Pure logic (parser, chunker, types): 90%+ coverage
- Discord-dependent code (Cogs, StatusManager): use mocks, 30%+ coverage
- **Never write implementation code without a corresponding test**

## Project Structure

```
claude_discord/          # Installable Python package
  __init__.py            # Public API exports
  protocols.py           # Shared protocols (DrainAware)
  main.py                # Standalone entry point
  bot.py                 # Discord Bot class
  cogs/
    claude_chat.py       # Main chat Cog (thread creation, message handling)
    skill_command.py     # /skill slash command with autocomplete
    webhook_trigger.py   # Webhook → Claude Code task execution (CI/CD)
    auto_upgrade.py      # Webhook → package upgrade + restart
    scheduler.py         # Scheduled task executor (SQLite-backed, master loop)
    _run_helper.py       # Shared Claude CLI execution logic (DRY)
  claude/
    runner.py            # Claude CLI subprocess manager
    parser.py            # stream-json event parser
    types.py             # Type definitions for SDK messages
  database/
    models.py            # SQLite schema
    repository.py        # Session CRUD operations
    notification_repo.py # Scheduled notification CRUD (REST API)
    task_repo.py         # Scheduled task CRUD (SchedulerCog)
  discord_ui/
    status.py            # Emoji reaction status manager (debounced)
    chunker.py           # Fence-aware message splitting
    embeds.py            # Discord embed builders
  ext/
    api_server.py        # REST API server (optional, requires aiohttp)
                         # Includes /api/tasks endpoints for SchedulerCog
  utils/
    logger.py            # Logging setup
tests/                   # pytest test suite
pyproject.toml           # Package metadata + dependencies
uv.lock                  # Dependency lock file
CONTRIBUTING.md          # Contribution guidelines
```

### Adding a New Cog

1. Create `claude_discord/cogs/your_cog.py`
2. If it runs Claude CLI, use `_run_helper.run_claude_in_thread()` — don't duplicate the streaming logic
3. Export from `claude_discord/cogs/__init__.py`
4. Add to `claude_discord/__init__.py` public API
5. Write tests in `tests/test_your_cog.py`

### Adding a New Discord UI Component

1. Add to the appropriate file in `claude_discord/discord_ui/`
2. Export from `__init__.py` if it's part of the public API
3. Test edge cases (empty strings, very long strings, Unicode, code blocks)

## Git & PR Workflow

- **Branch from `main`**: `feature/description`, `fix/description`, `docs/description`
- **CI must pass**: All 3 Python versions x (ruff check + ruff format + pytest)
- **No direct push to main**: Always create a PR
- **Squash merge preferred**: Keeps main history clean
- **Commit style**: `<type>: <description>` — types: feat, fix, refactor, docs, test, chore, security

## AI Agent Configuration

This project ships AI agent configs for all major tools:

| File | Tool | Purpose |
|------|------|---------|
| `CLAUDE.md` | Claude Code | Project context (this file) |
| `AGENTS.md` | OpenAI Codex | Symlink → CLAUDE.md |
| `.github/copilot-instructions.md` | GitHub Copilot | Condensed instructions |
| `.cursorrules` | Cursor | IDE-specific rules |

### Skills (`.claude/skills/`)

Project-specific skills that help AI agents work effectively on this codebase:

| Skill | Purpose |
|-------|---------|
| `tdd` | **Enforced** test-driven development — write tests FIRST, then implement |
| `verify` | Pre-commit quality gate (lint + format + test + security) |
| `add-cog` | Step-by-step guide to scaffold a new Cog |
| `security-audit` | Security checklist specific to subprocess/injection threats |
| `python-quality` | Python coding patterns and project conventions |
| `test-guide` | Testing patterns, mocking Discord objects, coverage goals |

### Commands (`.claude/commands/`)

| Command | Usage |
|---------|-------|
| `/verify` | Run full verification pipeline |
| `/new-cog <name>` | Scaffold a new Cog with tests |

### Hooks (`.claude/settings.json`)

- **PostToolUse (Edit/Write)**: Auto-format `.py` files with ruff after editing

## What Does NOT Belong Here

- Personal bot configuration (tokens, channel IDs, user IDs)
- Server-specific Cogs or workflows
- Direct Anthropic API calls (we use Claude Code CLI, not the API)
- Heavy dependencies that most users won't need
- Anything that requires secrets to import the package
