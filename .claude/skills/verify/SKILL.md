---
name: verify
description: Run full verification pipeline (lint, format, test, security) before committing
---

# Verify — Pre-Commit Quality Gate

Run this **before every commit** to ensure code quality and security.

## When to Activate

- Before creating a commit
- Before pushing to remote
- After making significant code changes
- When asked to "verify", "check", or "validate" the code

## Verification Pipeline

Run all steps in order. **Stop on first failure.**

### Step 1: Lint

```bash
uv run ruff check claude_discord/
```

If there are auto-fixable issues:

```bash
uv run ruff check --fix claude_discord/
```

### Step 2: Format

```bash
uv run ruff format --check claude_discord/
```

If formatting is needed:

```bash
uv run ruff format claude_discord/
```

### Step 3: Tests

```bash
uv run pytest tests/ -v --cov=claude_discord --cov-report=term-missing
```

All tests must pass. Review coverage for newly added code.

### Step 4: Security Audit

Before committing, check for these security concerns specific to this project:

1. **No shell=True**: Search for `shell=True` in any subprocess call — this is forbidden
2. **No hardcoded secrets**: Search for patterns like `token`, `secret`, `password`, `api_key` with string literal values
3. **Session ID validation**: Any new code accepting session IDs must validate with `^[a-f0-9\-]+$`
4. **Subprocess arguments**: All user input passed to Claude CLI must use `--` separator
5. **Environment stripping**: `_STRIPPED_ENV_KEYS` must include any new secret env vars

```bash
# Quick security grep
uv run ruff check claude_discord/ --select S  # bandit rules via ruff
```

### Step 5: Import Check

Verify the public API still works:

```python
python -c "from claude_discord import ClaudeRunner, ClaudeChatCog, SkillCommandCog, SessionRepository"
```

## Failure Protocol

- **Lint/Format failures**: Fix automatically, re-run
- **Test failures**: Fix the code (not the test, unless the test is wrong)
- **Security failures**: STOP. Do not commit. Fix the vulnerability first
- **Import failures**: Check `__init__.py` exports match actual module structure
