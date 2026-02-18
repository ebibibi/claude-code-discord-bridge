---
name: python-quality
description: Python coding patterns, idioms, and quality standards for claude-discord development
---

# Python Quality — Patterns & Standards

Coding standards and Pythonic patterns for claude-discord development. Based on PEP 8, modern Python 3.10+ idioms, and project conventions.

## When to Activate

- Writing new Python code in this project
- Reviewing code for quality
- Refactoring existing code

## Project-Specific Standards

### Type Hints (Mandatory)

```python
from __future__ import annotations  # Required in EVERY file

# Good: Full type annotations
async def run_claude_in_thread(
    thread: discord.Thread,
    runner: ClaudeRunner,
    repo: SessionRepository,
    prompt: str,
    session_id: str | None,
) -> str | None:
    ...

# Bad: Missing annotations
async def run_claude_in_thread(thread, runner, repo, prompt, session_id):
    ...
```

### Union Types (3.10+ Syntax)

```python
# Good: Modern syntax
def process(value: str | None) -> dict[str, list[int]]:
    ...

# Bad: Old-style typing
from typing import Optional, Dict, List
def process(value: Optional[str]) -> Dict[str, List[int]]:
    ...
```

### Dataclasses for State

```python
from dataclasses import dataclass, field

@dataclass
class SessionState:
    session_id: str | None = None
    thread_id: int = 0
    accumulated_text: str = ""
    active_tools: dict[str, discord.Message] = field(default_factory=dict)
```

### Error Handling

```python
import contextlib

# Discord API calls that may fail: suppress gracefully
with contextlib.suppress(discord.HTTPException):
    await message.add_reaction(emoji)

# Business logic: handle explicitly
try:
    async for event in runner.run(prompt):
        process(event)
except Exception:
    logger.exception("Failed to run CLI for thread %d", thread.id)
    await thread.send(embed=error_embed("An unexpected error occurred."))
```

### Logging (Not Print)

```python
import logging
logger = logging.getLogger(__name__)

# Good
logger.info("Starting CLI: %s", " ".join(args[:6]))
logger.warning("Session %s timed out after %ds", session_id, timeout)
logger.exception("Unexpected error in thread %d", thread.id)

# Bad — never use print() in library code
```

### Async Patterns

```python
# Always use create_subprocess_exec (not shell-based alternatives)
process = await asyncio.create_subprocess_exec(
    *args,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)

# Timeout handling
try:
    await asyncio.wait_for(process.wait(), timeout=5)
except TimeoutError:
    process.kill()

# Cleanup with try/finally
try:
    async for event in self._read_stream():
        yield event
finally:
    await self._cleanup()
```

### Import Organization

Enforced by ruff (`I` rule):

```python
# 1. Standard library
import asyncio
import logging
import re

# 2. Third-party
import discord
from discord.ext import commands

# 3. Local (relative)
from ..claude.runner import ClaudeRunner
from ..claude.types import MessageType
```

### Constants

```python
# Module-level, UPPER_SNAKE_CASE
DEBOUNCE_MS = 700
STALL_SOFT_SECONDS = 10
MAX_MESSAGE_LENGTH = 2000

# Frozen sets for immutable collections
_STRIPPED_ENV_KEYS = frozenset({"DISCORD_BOT_TOKEN", "CLAUDECODE"})
```

## File Organization

- **Max 400 lines per file** — extract if growing beyond
- **One class per file** for Cogs (they tend to grow)
- **Private modules**: prefix with `_` (e.g., `_run_helper.py`)
- **`__init__.py`**: Public API exports only, no logic

## Ruff Configuration

Project uses ruff with these rule sets (see `pyproject.toml`):

| Rule | Purpose |
|------|---------|
| E | pycodestyle errors |
| F | pyflakes |
| W | pycodestyle warnings |
| I | isort (import sorting) |
| N | pep8-naming |
| UP | pyupgrade (modern syntax) |
| B | flake8-bugbear |
| A | flake8-builtins |
| SIM | flake8-simplify |
