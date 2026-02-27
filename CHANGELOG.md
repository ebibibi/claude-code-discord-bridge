# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Tool result collapse threshold** — single-line tool outputs are now shown flat (no expand button); multi-line results (2+ lines) collapse behind an expand button. Previously, only outputs with 4+ lines were collapsed.

### Fixed
- **Empty tool output stuck embed** — tool calls that complete with no output (e.g. a command that exits silently) now properly clear the in-progress indicator on the embed instead of leaving it stuck.

## [1.6.0] - 2026-02-26

### Added
- **Cross-platform CI** — test matrix now covers Linux, Windows, and macOS × Python 3.10/3.11/3.12 (9 parallel jobs); `fail-fast: false` so all OS results are visible in one run (#192)
- **`_resolve_windows_cmd` unit tests** — 7 new tests covering npm wrapper parsing, fallback heuristic, OSError, missing node, and `_build_args` integration; all tests pass on every OS via `tmp_path` fixtures and `sys.platform` mocking (#192)

### Fixed
- **Windows compatibility** — resolved Windows npm `.cmd`/`.bat` Claude CLI wrapper to the underlying Node.js script so `create_subprocess_exec` can launch it; `add_signal_handler` (unsupported on Windows) now skipped on `win32` (#176)
- **Windows CI: UnicodeDecodeError in test_architecture** — `read_text()` calls now specify `encoding="utf-8"` explicitly; previously failed on Windows where the default encoding is locale-dependent (e.g. cp932)

## [1.5.0] - 2026-02-26

### Added
- **Collapsible tool results** — long tool outputs now collapse behind an expand button to keep threads readable (#171)
- **Todo embed pinned at bottom** — TodoWrite embed is delete-reposted so it always stays at the bottom of the thread (#170)

### Changed
- **Refactor: extract prompt_builder and session_sync modules** — split oversized files per project conventions; `claude_chat.py` (601→513 lines) with new `prompt_builder.py`, `session_manage.py` (702→577 lines) with new `session_sync.py` (#188)
- **Dead code cleanup** — removed 7 unused backward-compat re-exports from `_run_helper.py`, fixed duplicate exports in `discord_ui/__init__.py`, removed unused `_build_prompt` wrapper (#188)

### Fixed
- **Image-only messages** — sending a Discord message with only an image (no text) no longer crashes the bot; empty prompt with image URLs is now valid (#186, #187)
- **Image attachment support via stream-json** — images now passed as url-type blocks in `--input-format stream-json` mode instead of the removed `--image` flag (#178, #181, #182)
- **StopView runner reference** — Stop button now correctly targets the active runner after system-context clone (#175)
- **Discord system messages ignored** — thread renames, pins, and other system messages no longer trigger Claude (#172)
- **`is_error:true` result events** — error results from Claude CLI are now surfaced as error embeds in Discord (#184)
- **`stream_event` debug noise** — suppressed noisy debug logs for `stream_event` message type (#185)
- **CI: auto-version-bump** — release PRs with `[release]` tag no longer trigger spurious patch bumps; branch protection respected (#164, #167, #169, #173)

## [1.4.1] - 2026-02-24

### Fixed
- **Critical: CLI subprocess hang on Claude >=2.1.50** — `ClaudeRunner` spawned Claude CLI with `stdin=asyncio.subprocess.PIPE`, which causes Claude CLI >=2.1.50 to block indefinitely even in non-interactive (`-p`) mode. Switched to `stdin=asyncio.subprocess.DEVNULL`. This was causing all Bot-spawned sessions to create threads but never respond. `inject_tool_result()` already handles the missing stdin gracefully (logs a warning and returns) (#162)

### Changed
- Improved debug logging in `ClaudeRunner`: logs cwd at startup, PID after process creation, first 3 stdout lines, and EOF line count for easier troubleshooting (#162)
- README: reorganized Interactive Chat features from flat 23-item list into 5 scannable sub-sections with emoji headers (#160)

## [1.4.0] - 2026-02-22

### Added
- **TodoWrite live progress** — when Claude calls `TodoWrite`, a single Discord embed is posted to the thread and edited in-place on every subsequent update; shows ✅ completed, 🔄 active (with `activeForm` label), ⬜ pending; avoids thread flooding (#46)
- **Image attachments** — Discord image attachments are downloaded to temp files and passed to Claude via `--image`; up to 4 images per message, up to 5 MB each; temp files cleaned up after session (#43)
- **Bidirectional runner** — `ClaudeRunner` subprocess now opened with `stdin=PIPE`; new `inject_tool_result(request_id, data)` method writes JSON to stdin, enabling interactive tool-result injection (#50)
- **Plan Mode** — when Claude calls `ExitPlanMode`, the plan text is sent to Discord as an embed with Approve/Cancel buttons (`PlanApprovalView`); Claude's execution resumes only after approval; 5-minute timeout auto-cancels (#44)
- **Tool permission requests** — when Claude needs permission to execute a tool, Discord shows an embed with Allow/Deny buttons (`PermissionView`) showing tool name and JSON input; 2-minute timeout auto-denies (#47)
- **MCP Elicitation** — MCP server `elicitation` requests surfaced in Discord: form-mode generates a Modal with up to 5 fields from the JSON schema; url-mode shows a URL button with Done/Cancel; 5-minute timeout (#48)

### Changed
- `RunConfig` gains `image_paths: list[str] | None` field for per-invocation image passing
- `ClaudeRunner.__init__` accepts optional `image_paths` parameter; `_build_args()` appends `--image <path>` for each

## [1.3.0] - 2026-02-22

### Added
- **AI Lounge** (`LoungeChannel`) — shared Discord channel where concurrent Claude Code sessions announce themselves; hooks and concurrency notice injected automatically into every session's system prompt (#102, #107)
- **Startup resume** — bot restart auto-resumes interrupted sessions via `on_ready`; `pending_resumes` DB table tracks sessions that need resumption (#115)
- **`POST /api/spawn`** — programmatic Claude Code session creation from external callers (GitHub Actions, schedulers, other Claude sessions) without a Discord message trigger (#113)
- **`DISCORD_THREAD_ID` env injection** — subprocess env includes `DISCORD_THREAD_ID` so Claude can self-register for resume via `mark-resume` endpoint without knowing its session ID (#116)
- **Auto-mark on upgrade restart** — `AutoUpgradeCog` marks active sessions for resume before applying a package upgrade restart, so sessions survive bot upgrades (#126)
- **Auto-mark on any shutdown** — `cog_unload()` marks active sessions for resume on any bot shutdown (not just upgrades), ensuring no session is lost on `systemctl restart` (#128)
- **Automatic worktree cleanup** — `WorktreeCleanupCog` removes stale git worktrees left by finished sessions on a configurable interval (#124)
- **Stop button always at bottom** — Stop button is re-posted to the thread after each assistant message so it stays reachable without scrolling (#119)
- **`BridgeComponents.apply_to_api_server()`** — convenience method to wire `CoordinationChannel` and `SessionRegistry` into the REST API server; also auto-wired in `setup_bridge()` (#103)
- **`session_registry` in scheduler tasks** — `SchedulerCog` passes `session_registry` into spawned tasks so Claude can detect concurrent sessions before starting (#99)

### Changed
- **Layered architecture refactor** — large-scale internal refactor introducing `RunConfig` (immutable per-run config) and `EventProcessor` (stateful stream processor), replacing ad-hoc kwargs threading through the runner stack (#110)
- **Dead code removal** — eliminated unreachable branches and unused symbols identified by vulture, ruff, and coverage analysis (#104)
- **README rewrite** — README now leads with the concurrent multi-session development use case as the primary value proposition (#100)

### Fixed
- `session_start_embed` sent exactly once regardless of how many `SYSTEM` events arrive (#105)
- docs-sync webhook sent from `auto-approve.yml` after PR merge (was missing) (#106)
- Duplicate result text guarded by flag instead of fragile string comparison (#109)
- `spawn_session` made non-blocking via `asyncio.create_task` to avoid blocking the event loop (#117)
- `ServerDisconnectedError` from aiohttp on bot shutdown now handled gracefully (#120)
- Pre-commit hook exits with a clear error message when `uv` is not installed (#121)
- `asyncio.TimeoutError` in `auto_upgrade` now caught correctly on Python 3.10 (#123)
- `asyncio.TimeoutError` in `runner` and `ask_handler` now caught correctly on Python 3.10 (#130)

## [1.2.0] - 2026-02-20

### Added
- **Scheduled Task Executor** (`SchedulerCog`) — register periodic Claude Code tasks via Discord chat or REST API. Tasks are stored in SQLite and executed by a single 30-second master loop. No code changes needed to add new tasks (#90)
- **`/api/tasks` REST endpoints** — `POST`, `GET`, `DELETE`, `PATCH` for managing scheduled tasks. Claude Code calls these via Bash tool using `CCDB_API_URL` env var (#90)
- **`TaskRepository`** (`database/task_repo.py`) — CRUD for `scheduled_tasks` table with `get_due()`, `update_next_run()`, enable/disable support (#90)
- **`ClaudeRunner.api_port` / `api_secret` params** — when set, `CCDB_API_URL` (and optionally `CCDB_API_SECRET`) are injected into Claude subprocess env, enabling Claude to self-register tasks (#90)
- **`setup_bridge()` auto-discovery** — convenience factory that auto-wires `ClaudeRunner`, `SessionStore`, and `CoordinationChannel` from env vars; consumer smoke test in CI (#92)
- **Zero-config coordination** — `CoordinationChannel` auto-creates its channel from `CCDB_COORDINATION_CHANNEL_NAME` env var with no consumer wiring needed (#89)
- **Session Sync** — sync existing Claude Code CLI sessions into Discord threads with `/sync-sessions` command; backfills recent conversation messages into the thread (#30, #31, #36)
- **Session sync filters** — `since_days` / `since_hours` + `min_results` two-tier filtering, configurable thread style, origin filter for `/sessions` (#37, #38, #39)
- **LiveToolTimer** — live elapsed-time updates on long-running tool call embeds (#84, #85)
- **Coordination channel** — cross-session awareness so concurrent Claude Code sessions can see each other (#78)
- **Persistent AskView buttons** — bus routing and restart recovery for interactive Discord buttons (#81, #86)
- **AskUserQuestion integration** — `AskUserQuestion` tool calls render as Discord Buttons and Select Menus (#45, #66)
- **Thread status dashboard** — status embed with owner mention when session is waiting for input (#67, #68)
- **⏹ Stop button** — inline stop button in tool embeds for graceful `SIGINT` interrupt without clearing the session (#56, #61)
- **Token usage display** — cache hit rate and token counts shown in session-complete embed (#41, #63)
- **Redacted thinking placeholder** — embed shown for `redacted_thinking` blocks instead of silent skip (#49, #64)
- **Auto-discover registry** — bot auto-discovers cog registry; zero-config for consumers (#54)
- **Concurrency awareness** — multiple simultaneous sessions detected and surfaced in Discord (#53)
- **`upgrade_approval` flag** — gate `AutoUpgradeCog` restart behind explicit approval before applying updates (#60)
- **`restart_approval` mode** — `AutoUpgradeCog` can require approval before restarting the bot (#28)
- **DrainAware protocol** — cogs implementing `DrainAware` are auto-discovered and drained before bot restart (#26)
- **Pyright** — strict type checking added to CI pipeline (#22)
- **Auto-format on commit** — Python files are auto-formatted by ruff before every commit to prevent CI failures (#16)

### Changed
- **Test coverage**: 152 → 473 tests
- Removed `/skills` command; `/skill` with autocomplete is the sole entry point (#40)
- Tool result embeds show elapsed time in description rather than title field (#84, #88)

### Fixed
- Persistent AskView buttons survive bot restarts via bus routing (#81)
- SchedulerCog posts starter message before creating thread (#93, #94)
- GFM tables wrapped in code fences for consistent Discord rendering (#73, #76)
- Table header prepended to continuation chunks for Discord rendering (#73, #74)
- Markdown tables kept intact when chunking for Discord (#55, #57)
- Concurrency notice strengthened with diagnostic logging (#52, #62)
- Active Claude sessions drained before bot restart (#13, #15)
- `raw` field added to `StreamEvent` dataclass (#20)
- Extended thinking embed rendered as plain code block (#18, #19)
- `notify-upgrade` workflow triggered on PR close rather than push (#17)
- Auto-approve workflow waits for active webhook triggers before merging (#24)

## [1.1.0] - 2026-02-19

### Added
- **`/stop` command** — Stop a running Claude Code session without clearing the session ID, so users can resume by sending a new message (unlike `/clear` which deletes the session)
- **Attachment support** — Text-type file attachments (plain text, Markdown, CSV, JSON, XML, etc.) are automatically appended to the prompt; up to 5 files × 50 KB per file, 100 KB total
- **Timeout notifications** — Dedicated timeout embed with elapsed seconds and actionable guidance replaces the generic error embed for `SESSION_TIMEOUT_SECONDS` timeouts

### Changed
- **Test coverage**: 131 → 152 tests

## [1.0.0] - 2026-02-19

### Added
- **CI/CD Automation**: WebhookTriggerCog — trigger Claude Code tasks from GitHub Actions via Discord webhooks
- **Auto-Upgrade**: AutoUpgradeCog — automatically update bot when upstream packages are released
- **REST API**: Optional notification API server with scheduling support (requires aiohttp)
- **Rich Discord Experience**: Streaming text, tool result embeds, extended thinking spoilers
- **Bilingual Documentation**: Full docs in English, Japanese, Chinese, Korean, Spanish, Portuguese, and French
- **Auto-Approve Workflow**: GitHub Actions workflow to auto-approve and auto-merge owner PRs
- **Docs-Sync Workflow**: Automated documentation sync with infinite loop prevention (3-layer guard)
- **Docs-Sync Failure Notification**: Discord notification when docs-sync CI fails

### Changed
- **Architecture**: Evolved from mobile-only Discord frontend to full CI/CD automation framework
- **Test coverage**: 71 → 131 tests covering all new features
- **Codebase**: ~800 LOC → ~2500 LOC
- **README**: Complete rewrite reflecting GitHub + CI/CD automation capabilities

### Fixed
- Duplicate docs-sync PRs caused by merge conflict resolution triggering re-runs

## [0.1.0] - 2026-02-18

### Added
- Initial release — interactive Claude Code chat via Discord threads
- Thread = Session model with `--resume` support
- Real-time emoji status reactions (debounced)
- Fence-aware message chunking
- `/skill` slash command with autocomplete
- Session persistence via SQLite
- Security: subprocess exec only, session ID validation, secret isolation
- CI pipeline: Python 3.10/3.11/3.12, ruff, pytest
- Branch protection and PR workflow

[Unreleased]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/releases/tag/v0.1.0
