.PHONY: setup check-setup format check test ci pr dev-on dev-off

# One-time setup after cloning: install uv (if needed) and register the committed git hooks.
setup:
	@if ! command -v uv &>/dev/null; then \
		echo "❌ 'uv' is not installed. Install: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	fi
	git config core.hooksPath .githooks
	@echo "✅ Git hooks configured (.githooks/pre-commit active)"

# Verify that one-time setup has been completed (hooks configured + uv present).
check-setup:
	@if ! command -v uv &>/dev/null; then \
		echo "❌ 'uv' is not installed. Run: make setup"; \
		exit 1; \
	fi
	@if [ "$$(git config core.hooksPath)" != ".githooks" ]; then \
		echo "❌ Git hooks not configured. Run: make setup"; \
		exit 1; \
	fi
	@echo "✅ Development setup OK (uv present, hooks configured)"

# Auto-format all Python source files.
format:
	uv run ruff format claude_discord/ tests/

# Lint check (no auto-fix) — same as CI.
check:
	uv run ruff format --check claude_discord/ tests/
	uv run ruff check claude_discord/ tests/

# Run the full test suite.
test:
	uv run pytest tests/

# Full CI simulation: format check + lint + tests.
ci: check test

# Push current branch and open a PR (used after local dev testing is done).
pr:
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	git push -u origin "$$BRANCH"; \
	gh pr create --fill --web

# Enable dev mode: EbiBot loads claude_discord from this worktree on next restart.
dev-on:
	@echo "$$(pwd)" > $(HOME)/.ccdb-dev-worktree
	@echo "Dev mode ON — loading from $$(pwd)"
	sudo systemctl restart discord-bot

# Disable dev mode: EbiBot goes back to main tree on next restart.
dev-off:
	@rm -f $(HOME)/.ccdb-dev-worktree
	@echo "Dev mode OFF — back to main tree"
	sudo systemctl restart discord-bot
