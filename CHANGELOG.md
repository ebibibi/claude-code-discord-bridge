# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.0]: https://github.com/ebibibi/claude-code-discord-bridge/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/ebibibi/claude-code-discord-bridge/releases/tag/v0.1.0
