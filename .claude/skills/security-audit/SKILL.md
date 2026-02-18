---
name: security-audit
description: Security checklist specific to claude-discord — subprocess injection, env leaks, input validation
---

# Security Audit — claude-discord Specific

This project runs **arbitrary Claude Code sessions** triggered by Discord messages. Security is the #1 priority.

## When to Activate

- Before any commit that changes `runner.py`, `_run_helper.py`, or any Cog
- When adding new user-facing commands
- When modifying subprocess execution or argument passing
- When adding new environment variables or configuration
- Periodically as a full audit

## Threat Model

| Threat | Vector | Mitigation |
|--------|--------|------------|
| Command injection | User message passed to CLI args | `create_subprocess_exec` (no shell), `--` separator |
| Flag injection | Prompt starting with `-` | `--` separator before prompt |
| Session hijack | Fake session ID | Strict regex validation `^[a-f0-9\-]+$` |
| Skill injection | Malicious skill name | Strict regex validation `^[\w-]+$` |
| Secret exfiltration | Claude Bash tool reads env | Strip secrets from subprocess env |
| Nesting attack | Claude spawns another claude-discord | Strip `CLAUDECODE` from env |
| Token theft | Bot token in logs/errors | Never log tokens, strip from env |

## Checklist

### Subprocess Safety

- [ ] All subprocess calls use `asyncio.create_subprocess_exec` (NEVER `shell=True`)
- [ ] `--` separator is always placed before user-provided prompt text
- [ ] No string formatting/interpolation of user input into command strings
- [ ] Session IDs validated with `re.match(r"^[a-f0-9\-]+$", session_id)`
- [ ] Skill names validated with `re.match(r"^[\w-]+$", name)`

### Environment Security

- [ ] `_STRIPPED_ENV_KEYS` includes all secret environment variables
- [ ] `DISCORD_BOT_TOKEN` is stripped from subprocess env
- [ ] `CLAUDECODE` is stripped (prevents nesting detection bypass)
- [ ] No secrets in log output (check `logger.info/debug/warning/error` calls)
- [ ] `.env` file is in `.gitignore`

### Input Validation

- [ ] All user-provided strings are validated before use
- [ ] Discord message content is never directly interpolated into commands
- [ ] Thread IDs and channel IDs are validated as integers
- [ ] No user input reaches dangerous evaluation functions

### Error Handling

- [ ] Error messages don't leak internal paths or secrets
- [ ] Stack traces are logged (not sent to Discord)
- [ ] Failed sessions clean up properly (no zombie processes)

### Dependencies

- [ ] All dependencies are pinned in `uv.lock`
- [ ] No unnecessary dependencies
- [ ] discord.py is from the official PyPI package

## Quick Scan Commands

```bash
# Search for dangerous patterns
grep -rn "shell=True" claude_discord/
grep -rn "subprocess\.call" claude_discord/
grep -rn "subprocess\.run" claude_discord/

# Check that secrets are stripped
grep -n "_STRIPPED_ENV_KEYS" claude_discord/claude/runner.py

# Verify .env is gitignored
grep "\.env" .gitignore
```

## Response Protocol

- **CRITICAL** (injection, secret leak): Stop immediately. Fix before any other work.
- **HIGH** (missing validation): Fix before committing.
- **MEDIUM** (logging concern): Fix in the same PR.
- **LOW** (style/hardening): Track as a follow-up issue.
