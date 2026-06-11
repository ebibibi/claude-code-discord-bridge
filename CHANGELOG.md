# Changelog

Last updated: 2026-04-02

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Claude Fable 5 model option** — added `fable` to the selectable Claude models (`/model-set`, `/model-show`, and the `ccdb setup` model prompt). Fable 5 is Anthropic's state-of-the-art, token-efficient model and is passed through to the CLI as `claude --model fable`, so no API changes are needed. Like Opus, it is registered as a "slow" model in the statusline stall detector (`_SLOW_MODEL_KEYWORDS`) so its longer autonomous/thinking pauses don't trigger false stall warnings. The stale Opus label was corrected to "Opus 4.8". (Mythos 5 is intentionally not exposed — it is restricted to trusted-access programs.)
- **`POST /api/run` — headless one-shot AI runs** — the non-interactive, no-Discord sibling of `/api/spawn`. Dispatches a single prompt to an AI engine as a background job and returns a `run_id`; `GET /api/run/{run_id}` polls for `{status, result, error, backend, model}`. Built for external callers (browser extensions, scripts) that want "send a prompt → get generated text back" without a Discord thread. **Engine-neutral by construction**: the handler has no claude/codex branches — `create_backend(backend, model)` resolves the runner and a small `collect_oneshot` collector drives `SessionBackend.run()` to its RESULT event, so the same endpoint works for Claude, Codex, or any future backend. `backend`/`model` default to the bot's current selection (`BackendSettings`); `skill`/`cwd`/`system_prompt` are optional. The prompt is validated (≤ 64 KB, skill name `^[\w-]+$`) and is **not** persisted — only the engine selection, status, and final text are stored (`RunRepository`, capped at 200 rows). Auto-wired via `BridgeComponents.apply_to_api_server()` (Zero-Config: existing consumers gain the endpoint by updating the package). Requires the Bearer token when `api_secret` is set.
- **Automated dependency maintenance** — added `.github/dependabot.yml` (weekly grouped version updates for the `uv` Python ecosystem and GitHub Actions) plus an `auto-merge-dependabot` job in `auto-approve.yml`. The job auto-approves and enables auto-merge for patch/minor Dependabot PRs once CI passes, and flags major bumps for manual review. Dependabot merges intentionally skip the EbiBot-restart webhook (the lock change reaches the running bot on its next natural restart via `pre-start.sh`), so routine dependency upkeep never disrupts active sessions.
- **API provider indicator** — After each session, the statusline footer shows a `🔗 API: <provider>` line indicating which API endpoint the Claude Code CLI is actually using: `Anthropic API (direct)`, `AWS Bedrock`, `Google Vertex AI`, `Azure AI Foundry`, or a custom base URL. The label is derived from the final subprocess environment (`_build_env()`), so CLI env overlays (`CCDB_CLI_ENV_FILE`) and systemd-provided variables are reflected accurately. It is shown even when no `statusLine` is configured, so "which API am I using right now" stays visible after every turn. Adds the `detect_api_provider()` helper (exported from `claude_code_core`) and `SessionBackend.describe_api()` on both `ClaudeRunner` and `CodexRunner`.

### Fixed
- **Sessions no longer hang "running" forever when the model asks for confirmation (plan approval / thinking display restored)** — The Claude Code CLI stopped populating `stop_reason` on `assistant`-type stream-json messages; the real completion signal moved to the trailing `message_delta` `stream_event` (which ccdb ignores). The parser still derived `is_partial = (stop_reason is None)`, so **every** assembled content block was mis-flagged as a streaming partial. That silently disabled all `not is_partial`-gated handlers in the event processor — extended-thinking display and, critically, **plan approval (`ExitPlanMode`)**. With the Approve/Cancel UI suppressed, the CLI blocked indefinitely waiting for an answer it could never receive, so the Discord thread sat at "⏺ Session running" with no visible prompt. This surfaced most often with reasoning-heavy models such as **Fable 5** that present plans for confirmation. Each `assistant` message ccdb receives is now correctly treated as a complete content block (token-level partials arrive only as `stream_event`s, which we don't act on). As a side effect, completed text blocks post directly instead of via repeated in-place edits, easing Discord edit rate-limit (HTTP 429) pressure. An explicit `stop_reason` is still honoured when present.
- **Interactive input prompts now mention the requester** — Plan approval, permission
  requests, MCP elicitation, and AskUserQuestion messages mention the user who started
  the session, making it clear that Claude is waiting for button/form input instead of
  still running. Passive controls such as Stop and tool-result expand buttons remain
  silent. Mentions use a restricted `allowed_mentions` payload so only the target user
  can be notified (#419).
- **`pre-start.sh` skipped `git pull` when untracked files were present** — the local-dev-mode guard treated *any* `git status --porcelain` output as a signal to skip the pull. The bot-generated `logs/` directory (from the optional rotating file log handler) showed up as an untracked entry, so the guard silently skipped every pull and a stale checkout persisted across restarts. The guard now considers only *tracked* changes (`--untracked-files=no`), and `logs/` is gitignored.

### Security
- **Cleared all open Dependabot alerts (9)** — bumped `pillow` 12.1.1 → 12.2.0 (2 high-severity advisories), `pytest` 9.0.2 → 9.0.3, `python-dotenv` 1.2.1 → 1.2.2, `idna` 3.11 → 3.18, and `Pygments` 2.19.2 → 2.20.0 in `uv.lock`. Minimum-version floors in `pyproject.toml` were raised (`pillow>=12.2.0`, `python-dotenv>=1.2.2`, `pytest>=9.0.3`) so the vulnerable ranges stay out of future dependency resolutions.

## [3.0.0] - 2026-05-15

### Added
- **OpenAI Codex backend** — `SessionBackend` Protocol with `ClaudeRunner` and `CodexRunner` implementations. Select via `CCDB_BACKEND=claude|codex` (default: `claude`). Both runners satisfy the same async-streaming contract.
- **Backend identification in embeds** — `session_start_embed` title prefix and accent color reflect the active backend (Claude = blurple, Codex = OpenAI teal). `session_complete_embed` prepends a `🧠 <backend> · <model>` chip.
- **`/backend [name] [scope]`** — show or switch backend at runtime. Persists via `SettingsRepository` so the choice survives bot restart. `scope` is `thread`-aware: invoked inside a thread defaults to thread scope, otherwise global.
- **`/model [name] [scope]`** — show or switch the per-backend model. Same scope semantics as `/backend`. Stored separately for each backend so switching backend automatically falls back to the previously-set model for that backend.
- **`CCDB_*` env-var namespace** — unified config under `CCDB_BACKEND`, `CCDB_MODEL`, `CCDB_COMMAND`, `CCDB_CLAUDE_COMMAND`, `CCDB_CODEX_COMMAND`, `CCDB_PERMISSION_MODE`, `CCDB_WORKING_DIR`, `CCDB_ALLOWED_TOOLS`, `CCDB_EFFORT`, `CCDB_CHANNEL_IDS`, `CCDB_MONITOR_ALL_CHANNELS`, `CCDB_DANGEROUSLY_SKIP_PERMISSIONS`. Original `CLAUDE_*` variables continue to work as fallback.
- **`/goal` slash command** — autonomous goal-driven sessions that loop until a user-supplied completion condition is met.
- **`BackendFactory`** — runtime authority for constructing `ClaudeRunner` / `CodexRunner` on demand from static config. Used by `/backend` to swap the active runner without restarting the bot.
- **`BackendSettings`** — thin layer over `SettingsRepository` that resolves the active backend/model with thread > global > env precedence and persists writes from the slash commands. 8 unit tests cover resolution + mutation.

### Changed
- **Project display name** — "Claude Code Discord Bridge" → "Claude & Codex Discord Bridge". Repo, package, and Python module names (`claude-code-discord-bridge`, `claude_discord`, `claude_code_core`) are unchanged to preserve install / import compatibility.
- **`/help` embed title** — now "🤖 Claude & Codex Bot — Help".
- **`SessionBackend` Protocol** — extended to declare `command`, `api_port`, `timeout_seconds`, `dangerously_skip_permissions`, `allowed_tools`, `_build_env()`, and a non-`async` `run()` signature (matches how async generator functions are typed). All consumers (`claude_chat`, `skill_command`, `scheduler`, `webhook_trigger`, `cog_loader`, `discord_ui/views.StopView`, `cogs/run_config.RunConfig`) now type their `runner` parameter as `SessionBackend` instead of `ClaudeRunner`.
- **`CodexRunner.__init__`** — accepts (and stores) `allowed_tools` for Protocol conformance; the field is currently a no-op in argv construction.

### Notes
- Thread-scoped backend/model overrides are persisted by `BackendSettings` and the `/backend` / `/model` commands set them correctly, but `ClaudeChatCog` still spawns sessions via `self.runner.clone(...)` and therefore does not yet consume them. A follow-up will swap that for `BackendFactory.build(...)` so per-thread overrides take effect at session start. Global switches are already in effect immediately.

## [2.2.0] - 2026-04-26

### Added
- **Session search** — `SessionRepository.search()` with keyword search across summary and working_dir, origin filtering, and thread ID include/exclude support
- **Enhanced `/resume` command** — optional `query` parameter for keyword search and `filter` parameter to show only orphaned (deleted thread) sessions
- **Working directory tracking** — Discord chat sessions now save `working_dir` to the database (previously only CLI-synced sessions saved this)

### Changed
- **ResumeSelectView** — shows full `working_dir` path in session descriptions instead of just the last directory component

## [2.1.24] - 2026-04-02

### Added
- **CLI env overlay** (`CCDB_CLI_ENV_FILE`) — inject environment variables into CLI subprocesses via an external `KEY=VALUE` file, read on every CLI invocation without bot restart. Useful for temporary API routing (e.g., Azure Foundry switching) (#359)
- **Job failure triage** (`JobFailureTriageCog`) — auto-investigates scheduler job failures (#357)

## [2.1.0] - 2026-03-15

### Added
- **Chat-only mode** (`chat_only_channel_ids` / `CHAT_ONLY_CHANNEL_IDS`) — when a channel is configured as chat-only, only text responses are shown to Discord; tool embeds, thinking blocks, session start/complete embeds, todo lists, and other technical details are hidden. Permission requests and AskUserQuestion are always shown regardless. Useful for public channels where non-technical users are watching (#315)
- **Poll parameter for `/api/notify`** — REST API notification endpoint now accepts a `poll` parameter to create Discord polls alongside notification messages (#312)
- **Plain text format for `/api/notify`** — `format: "text"` option sends notifications as plain text instead of embeds, useful for simple messages (#311)
- **Thread ID in lounge messages** — lounge messages now include `thread_id` for self-identification after context compaction (#305)
- **Dev worktree mode** — `make dev-on` / `make dev-off` for testing code changes on EbiBot before merging PRs; uses `sys.meta_path` hook to redirect imports to worktree (#294)
- **StatusLine display** — configured `statusLine` shown in Discord after each session (#296)
- **AlertResponderCog** — generic alert-monitoring Cog for custom deployments (#289)
- **Plugin skill auto-discovery** — `/skill` command now auto-discovers skills from installed plugins (#292)

### Changed
- **Dev workflow documentation** — clarified that local testing with `make dev-on` must happen before PR merge, not after

### Fixed
- **Context compaction interrupt** — interrupt cloned runner on `compact_boundary`, not original (#306, #307)
- **Error embed detail** — show exception detail in error embed and handle non-dict todo items (#310)
- **CLI session import** — wire `CLI_SESSIONS_PATH` env, UTF-8 session files, `working_dir` on resume (#302)
- **CI YAML parse error** — resolve YAML parse error in `ci.yml` broken since cc9e2d8 (#298)
- **Auto-approve polling** — extend polling to 15min and cancel stale runs (#297)
- **Thread title cleaning** — harden against noisy model output (#291)
- **`/rewind` implementation** — true rewind with JSONL truncation and turn-selection UI (#293)
- **Auto-merge filter** — exclude external-issue labeled PRs from auto-merge (#286)
- **SkillCommandCog clone** — pass `thread_id` to `runner.clone()` (#284)

## [2.0.0] - 2026-03-06

### Added
- **`/context` slash command** — shows context window usage % with a visual progress bar and autocompact warning when nearing the 83.5% threshold (#265)
- **`/usage` slash command** — shows Claude API rate limit utilization with percentage bar and time-until-reset countdown (#267)
- **`rate_limit_event` parser** — stream-json `rate_limit_event` messages are now parsed and persisted to a new `usage_stats` DB table (upserted per `rate_limit_type`); consumers get up-to-date usage data with zero config (#266)
- **Context stats persistence** — `context_window` and `context_used` are saved to the `sessions` table after each session completes; powers the `/context` command and `/rewind` confirmation

### Changed
- **`/rewind` confirmation now shows context % at reset time** — when context stats are available, the reset message includes "Context was X% full at reset." to help users understand why the session was rewound (#242)
- **`/fork` uses `--fork-session` CLI flag** — forks now create a truly independent session copy with a new session ID; eliminates the `UNIQUE INDEX` violation that crashed the bot when both threads tried to save the same session ID (#243)
- **DB migration: `idx_sessions_session_id` is no longer UNIQUE** — allows forked sessions to coexist without constraint violations; existing databases are upgraded automatically on startup

### Fixed
- **Scheduler sessions are now resumable** — `SchedulerCog` passes `session_repo` to `RunConfig` so sessions created by scheduled tasks are persisted to the DB and can be resumed with follow-up messages (#264)

### Database
- New `usage_stats` table (one row per `rate_limit_type`; upserted on every `rate_limit_event`)
- New columns `context_window` and `context_used` on `sessions` table
- `idx_sessions_session_id` changed from UNIQUE to non-unique index

## [1.9.0] - 2026-03-05

### Added
- **`/tools` slash commands** — `/tools-show`, `/tools-set`, `/tools-reset` for runtime tool permission management from Discord; no bot restart required (#235)
- **`/rewind` and `/fork` slash commands** — rewind a session to an earlier checkpoint, or fork the conversation into a new thread (#239)
- **Thread inbox with auto-classification** — incoming messages in inbox mode are automatically categorized by Claude (`claude -p`) for smarter routing (#249)
- **`THREAD_AUTO_RENAME`** — optionally let Claude AI rename thread titles based on session content; keeps threads self-documenting without manual effort (#257)
- **`CLAUDE_ALLOWED_TOOLS` usage guide** — comprehensive documentation with real-world examples showing how to lock down or expand tool access per deployment (#233)

### Changed
- **All user-facing and Claude-facing strings translated to English** — system prompts, embed labels, and UI text unified in English for broader contributor accessibility (#255)

### Fixed
- **Log injection prevention** — `api_server.py` now sanitizes log messages; ANSI escape sequences and control characters in user-supplied data can no longer corrupt log output (#254)
- **Safer bot-restart resume prompt** — after a bot restart, Claude reports its current state and asks for confirmation before continuing, rather than silently auto-resuming mid-task (#252)
- **Duplicate user mention removed** — session-complete message no longer mentions the requester twice when both `requester_id` and the session owner are set (#244)
- **ebibot-upgrade webhook suppressed** for docs-sync and auto-bump PRs, preventing spurious upgrade cycles that re-triggered on their own merges (#246, #247)
- **Redundant `notify-upgrade` workflow removed** — consolidates upgrade notification into a single path (#251)
- **`asyncio.TimeoutError` on Python 3.10** — now caught correctly everywhere; Python 3.10 raises a different exception class than 3.11+ (#260)
- **`/tools` Ask modal feedback** — "Other" free-text modal submission now updates the prompt message immediately for visual confirmation (#238)

### Security
- **CodeQL scanning** — GitHub Actions workflow added for static analysis of Python source and Actions workflow injection vulnerabilities
- **Command injection prevention in CI** — `notify-failure` workflow now uses `${{ env.VAR }}` instead of direct `${{ github.event.* }}` interpolation in `run:` steps, closing a shell-injection path

### CI / Testing
- **Branch coverage enforced** — `--cov-branch` flag added to CI pytest run; 75% branch coverage required as a merge gate, catching logic paths that line coverage misses (#260)
- **Auto version bump reliability** — switched to PR-based flow with `ADMIN_PAT` to reliably bypass branch protection rulesets on direct pushes (#227, #230)

## [1.8.0] - 2026-03-02

### Added
- **Custom Cog loader** — load external Cog files from any directory via `CUSTOM_COGS_DIR` env or `--cogs-dir` CLI flag; each `.py` file exposes `async def setup(bot, runner, components)`; fault-isolated (one Cog failure doesn't block others) (#220)
- **EbiBot example** (`examples/ebibot/`) — real-world reference implementation with 4 self-contained custom Cogs: ReminderCog, WatchdogCog, AutoUpgradeCog, DocsSyncCog (#220)
- **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` env var** — skip all CLI permission checks without code changes; recommended for ccdb deployments where access is already gated via `allowed_user_ids` (#215)
- **Permission Modes documentation** — README section explaining how `-p` mode interacts with permission modes and why `DANGEROUSLY_SKIP_PERMISSIONS` is the practical choice for ccdb (#218, #219)
- **systemd service file** — production-ready `discord-bot.service` and `scripts/pre-start.sh` for deploying ccdb as a systemd service with auto-update on restart

### Changed
- **`main.py` rewritten** — now uses `setup_bridge()` for full Cog auto-setup instead of manual registration; supports all env vars including `CUSTOM_COGS_DIR`, `CLAUDE_CHANNEL_IDS`, `API_HOST`, `API_PORT`, `CLAUDE_ALLOWED_TOOLS`
- **`cli.py` updated** — `ccdb start` accepts `--cogs-dir` argument

### Fixed
- **Silent exception suppression** — replaced `contextlib.suppress(Exception)` with proper logging + narrowed exception types so errors are visible in logs (#216)
- **Pyright type errors in `main.py`** — `load_config()` return type was `dict[str, str]` but `dangerously_skip_permissions` was a `bool`; moved bool conversion to call site (#223)
- **Branch protection**: added required CI status checks (`test (ubuntu-latest, 3.10/3.11/3.12)`) so PRs with failing CI can no longer be merged

## [1.7.5] - 2026-03-02

### Added
- **File attachment delivery** — when Claude writes files during a session, listing their absolute paths in `.ccdb-attachments` (one per line) causes the bot to upload them to Discord on session complete; opt-in, zero config for consumers (#195, #196)
- **`/help` slash command** — lists all registered slash commands dynamically; CI guard prevents stale command lists from being merged (#199, #200)
- **Mention requester after significant work** — when `requester_id` is set and Claude uses ≥ 3 tool calls, the requesting user is mentioned in the session-complete message so they notice the result in busy servers (#198)
- **Multi-channel support (`claude_channel_ids`)** — accepts a comma-separated list of channel IDs so one bot instance can serve multiple channels (#204)
- **Mention-only channel mode** — a channel can be configured to only respond when the bot is directly @-mentioned, leaving other messages alone (#204)
- **Inline-reply channel mode** — a channel can be configured to reply inline (no thread created), suitable for simple one-off commands (#204)
- **Real-time tool timer** — in-progress tool embeds now show elapsed seconds updated every 5 s so long-running commands are visually trackable (#194)
- **CI failure Discord notification** — GitHub Actions posts a Discord message when any CI job fails, with branch name and run URL (#208)
- **Weekly stale branch cleanup** — a scheduled GitHub Actions workflow deletes branches from closed PRs using the GitHub API (handles squash-merge branches correctly) (#208, #209)

### Changed
- **Tool result collapse threshold** — single-line tool outputs are now shown flat (no expand button); multi-line results (2+ lines) collapse behind an expand button. Previously, only outputs with 4+ lines were collapsed.
- **UpgradeApprovalView re-post** — the upgrade approval button is deleted and re-sent after each upgrade step so it stays at the bottom of the channel and remains visible (#201)
- **Text attachment size limit raised** — per-file limit increased from 50 KB to 200 KB; total limit from 100 KB to 500 KB, matching Discord's auto-conversion of long pastes (#213)

### Fixed
- **Empty tool output stuck embed** — tool calls that complete with no output (e.g. a command that exits silently) now properly clear the in-progress indicator on the embed instead of leaving it stuck.
- **Coordination channel session-end message** — now uses thread ID instead of title to identify sessions, preventing confusion when threads are renamed.
- **Streaming message truncation** — long streaming messages are no longer cut off with `...`; the full content is always forwarded (#203).
- **Pyright type errors for `Thread | TextChannel`** — inline-reply mode introduced `TextChannel` as a valid thread target; type annotations in six internal modules updated to reflect this (#206).
- **Text attachments with missing `content_type`** — Discord auto-converts long pastes to `.txt` files with `content_type=None`; the bot now falls back to file-extension detection so these attachments are read correctly (#211).
- **Large text attachments silently dropped** — text attachments exceeding the old 50 KB limit were skipped without notifying Claude; they are now truncated with a visible notice so Claude always sees the content (#213).

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

[Unreleased]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v2.0.5...v2.1.0
[2.0.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.9.0...v2.0.5
[1.9.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.7.5...v1.8.0
[1.7.5]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.6.0...v1.7.5
[1.6.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/releases/tag/v0.1.0
