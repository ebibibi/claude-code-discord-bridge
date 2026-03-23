# claude-code-discord-bridge (ccdb)

Discord frontend for Claude Code CLI. **This is a framework (OSS library), not a personal bot.**

**略称: ccdb** (claude-code-discord-bridge)

## Framework vs Instance

- **claude-code-discord-bridge** (this repo) = reusable OSS framework. No personal config, no secrets, no server-specific logic.
- Personal instances (e.g. EbiBot) use the custom Cog loader (`CUSTOM_COGS_DIR` / `--cogs-dir`) to add their own Cogs. See `examples/ebibot/` for the reference implementation.
- When adding features: if it's useful to anyone → add here. If it's personal workflow → add as a custom Cog.

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

### EbiBot のデプロイ（⚠️ 手動操作が必要と断言する前に読め）

「手動で `git pull` が必要」「`systemctl restart` が必要」等と言う前に、
`scripts/pre-start.sh`・`.github/workflows/`・`examples/ebibot/cogs/` を読むこと。
自動化されている可能性が高い。

### 開発フロー（worktree + ローカルテスト）

EbiBot は `/home/ebi/claude-code-discord-bridge/` から直接起動する（systemd `WorkingDirectory`）。
コード変更をPRマージ前に EbiBot で動作確認するための **dev worktree モード**が用意されている。

```bash
# 1. worktreeを作成してブランチで作業（Claude Codeが自動で行う）
git worktree add ../wt-my-feature -b feat/my-feature

# 2. worktreeで実装・ユニットテスト
cd /home/ebi/wt-my-feature
uv run pytest tests/ -v

# 3. dev modeを有効化してDiscord上で動作確認
make dev-on    # ~/.ccdb-dev-worktree にパスを書いてbotを再起動
# → Discord上でEbiBotを実際に操作してテスト
# → ユーザーが「OK」と確認するまでこのフェーズを続ける

# 4. 動作確認OKの後、dev modeを解除してPR作成・マージ
make dev-off   # ~/.ccdb-dev-worktree を削除してbotを再起動
make pr        # ブランチをpushしてGitHub PRを作成
# → PRマージは動作確認が完了した後に行う。先にマージしない！
```

**仕組み（`pre-start.sh` の実装）:**

1. `uv sync` 実行後、`_ccdb_dev_hook.py` と `_ccdb_dev_hook.pth` を venv の site-packages に配置する
2. `_ccdb_dev_hook.pth` が Python 起動時に `import _ccdb_dev_hook` を実行する
3. `_ccdb_dev_hook.py` が `sys.meta_path[0]` に `_Finder` を挿入する
4. `_Finder` が `~/.ccdb-dev-worktree` を読み、`claude_discord` のimportをworktreeに横取りする

`sys.meta_path` フックは `python -m` の CWD-first（`sys.path[0] = ''`）より優先される。
`.pth` / `PYTHONPATH` / `sitecustomize.py` では CWD に勝てないため、この方式を採用した。

**通常起動（本番モード）:**

`~/.ccdb-dev-worktree` が存在しない場合、フックは何もしない。
mainブランチで変更なしの場合、`pre-start.sh` が `git pull` して最新コードを取得する。

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
  cli.py                 # CLI entry point (ccdb setup/start commands)
  main.py                # Standalone entry point (setup_bridge + custom cog loader)
  setup.py               # setup_bridge() — one-call Cog wiring
  cog_loader.py          # Dynamic custom Cog loader (CUSTOM_COGS_DIR / --cogs-dir)
  bot.py                 # Discord Bot class
  protocols.py           # Shared protocols (DrainAware)
  concurrency.py         # Worktree instructions + active session registry
  lounge.py              # AI Lounge prompt builder
  session_sync.py        # CLI session discovery and import
  worktree.py            # WorktreeManager — safe git worktree lifecycle
  cogs/
    claude_chat.py       # Main chat Cog (thread creation, message handling)
    skill_command.py     # /skill slash command with autocomplete
    session_manage.py    # /sessions, /sync-sessions, /resume, /resume-info, /sync-settings
    session_sync.py      # Thread-creation and message-posting for sync-sessions
    prompt_builder.py    # build_prompt_and_images() — pure function
    webhook_trigger.py   # Webhook → Claude Code task execution (CI/CD)
    auto_upgrade.py      # Webhook → package upgrade + drain-aware restart
    scheduler.py         # Scheduled task executor (SQLite-backed, master loop)
    event_processor.py   # EventProcessor — state machine for stream-json events
    run_config.py        # RunConfig dataclass — bundles all CLI execution params
    _run_helper.py       # Thin orchestration layer (run_claude_with_config)
  claude/
    runner.py            # Claude CLI subprocess manager
    parser.py            # stream-json event parser
    types.py             # Type definitions for SDK messages
  coordination/
    service.py           # Posts session lifecycle events to shared channel
  database/
    models.py            # SQLite schema
    repository.py        # Session CRUD operations
    task_repo.py         # Scheduled task CRUD (SchedulerCog)
    ask_repo.py          # Pending AskUserQuestion CRUD
    notification_repo.py # Scheduled notification CRUD (REST API)
    lounge_repo.py       # AI Lounge message CRUD
    resume_repo.py       # Startup resume CRUD (pending resumes)
    settings_repo.py     # Per-guild settings
  discord_ui/
    status.py            # Emoji reaction status manager (debounced)
    chunker.py           # Fence- and table-aware message splitting
    embeds.py            # Discord embed builders
    views.py             # Stop button, ToolSelectView, and shared UI components
    ask_bus.py           # Event bus for AskUserQuestion communication
    ask_view.py          # Buttons/Select Menus for AskUserQuestion
    ask_handler.py       # collect_ask_answers() — AskUserQuestion UI + DB lifecycle
    streaming_manager.py # StreamingMessageManager — debounced message edits
    tool_timer.py        # LiveToolTimer — elapsed time counter
    thread_dashboard.py  # Live pinned embed showing session states
    plan_view.py         # Approve/Cancel buttons for Plan Mode
    permission_view.py   # Allow/Deny buttons for tool permission requests
    elicitation_view.py  # Discord UI for MCP elicitation
    file_sender.py       # File delivery via .ccdb-attachments
    thread_renamer.py    # suggest_title() — background claude -p call for auto thread renaming
  ext/
    api_server.py        # REST API server (optional, requires aiohttp)
  utils/
    logger.py            # Logging setup
tests/                   # pytest test suite
examples/
  ebibot/                # Real-world example: personal bot with custom Cogs
    cogs/                # ReminderCog, WatchdogCog, AutoUpgradeCog, DocsSyncCog
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

### Custom Cog Protocol (for external Cogs loaded via `--cogs-dir`)

Custom Cog files are loaded by `cog_loader.py` from the directory specified by `CUSTOM_COGS_DIR` env or `--cogs-dir` CLI flag. Each `.py` file must expose:

```python
async def setup(bot, runner, components):
    """Called by load_custom_cogs().

    Args:
        bot: discord.ext.commands.Bot instance
        runner: ClaudeRunner (may be None if Claude chat is disabled)
        components: BridgeComponents (session_repo, task_repo, etc.)
    """
    await bot.add_cog(MyCog(bot))
```

Rules:
- Files prefixed with `_` are skipped
- Load order is deterministic (`sorted()` by filename)
- One Cog's failure is logged and skipped — never blocks others
- `examples/ebibot/cogs/` is the canonical reference implementation

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
