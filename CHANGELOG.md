# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-02-20

### Added
- **Scheduled Task Executor** (`SchedulerCog`) — register periodic Claude Code tasks via Discord chat or REST API. Tasks are stored in SQLite and executed by a single 30-second master loop. No code changes needed to add new tasks (#90)
- **`/api/tasks` REST endpoints** — `POST`, `GET`, `DELETE`, `PATCH` for managing scheduled tasks. Claude Code calls these via Bash tool using `CCDB_API_URL` env var
- **`TaskRepository`** (`database/task_repo.py`) — CRUD for `scheduled_tasks` table with `get_due()`, `update_next_run()`, enable/disable support
- **`ClaudeRunner.api_port` / `api_secret` params** — when set, `CCDB_API_URL` (and optionally `CCDB_API_SECRET`) are injected into Claude subprocess env, enabling Claude to self-register tasks
- **`setup_bridge()` auto-discovery** — convenience factory that auto-wires `ClaudeRunner`, `SessionStore`, and `CoordinationChannel` from env vars; consumer smoke test in CI (#92)
- **Zero-config coordination** — `CoordinationChannel` auto-creates its channel from `CCDB_COORDINATION_CHANNEL_NAME` env var with no consumer wiring needed (#89)
- **LiveToolTimer** — live elapsed-time updates on long-running tool call embeds (#84, #85)
- **Coordination channel** — cross-session awareness so concurrent Claude Code sessions can see each other (#78)
- **Persistent AskView buttons** — bus routing and restart recovery for interactive Discord buttons (#81, #86)
- **AskUserQuestion integration** — `AskUserQuestion` tool calls render as Discord Buttons and Select Menus (#45, #66)
- **Thread status dashboard** — owner mention when session is waiting for input (#67, #68)
- **Token usage display** — cache hit rate and token counts shown in session-complete embed (#41, #63)
- **Redacted thinking placeholder** — embed shown for `redacted_thinking` blocks instead of silent skip (#49, #64)
- **Auto-discover registry** — bot auto-discovers cog registry; zero-config for consumers (#54)
- **Concurrency awareness** — multiple simultaneous sessions detected and surfaced in Discord (#53)
- **Architecture decisions recorded** — CLAUDE.md §Key Design Decisions #7-9 document the REST API control plane pattern and dynamic scheduler design rationale

### Changed
- **Test coverage**: 152 → 473 tests
- Tool result embeds show elapsed time in description rather than title field (#84, #88)

### Fixed
- Persistent AskView buttons survive bot restarts via bus routing (#81)
- SchedulerCog posts starter message before creating thread (#93, #94)
- GFM tables wrapped in code fences for consistent Discord rendering (#73, #76)
- Table header prepended to continuation chunks (#73, #74)
- Markdown tables kept intact when chunking for Discord (#55, #57)
- Concurrency notice strengthened with diagnostic logging (#52, #62)

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

[Unreleased]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/releases/tag/v0.1.0
