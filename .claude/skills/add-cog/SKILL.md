---
name: add-cog
description: Step-by-step guide to add a new discord.py Cog to the framework
---

# Add Cog — Scaffold a New Discord.py Cog

## When to Activate

- Adding new Discord bot functionality
- Creating a new slash command or event handler
- When asked to "add a cog", "create a command", or "add a feature"

## Steps

### 1. Create the Cog File

Create `claude_discord/cogs/your_cog.py`:

```python
"""Short description of what this Cog does."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class YourCog(commands.Cog):
    """Docstring explaining the Cog's purpose."""

    def __init__(
        self,
        bot: commands.Bot,
        # Add dependencies as constructor params (dependency injection)
    ) -> None:
        self.bot = bot

    # Add commands and listeners here
```

### 2. If It Runs Claude CLI

Use the shared helper — **never duplicate the streaming logic**:

```python
from ._run_helper import run_claude_in_thread

# In your command handler:
runner = self.runner.clone()  # Always clone for concurrent safety
await run_claude_in_thread(
    thread=thread,
    runner=runner,
    repo=self.repo,
    prompt=user_input,
    session_id=existing_session_id,
)
```

### 3. Export from Package

Add to `claude_discord/cogs/__init__.py`:

```python
from .your_cog import YourCog
```

Add to `claude_discord/__init__.py`:

```python
from .cogs.your_cog import YourCog
# And add "YourCog" to __all__
```

### 4. Write Tests

Create `tests/test_your_cog.py`:

- Test command validation (invalid inputs, edge cases)
- Test authorization checks
- Mock Discord objects (`discord.Interaction`, `discord.TextChannel`, etc.)
- Test error handling paths

### 5. Verify

Run the verify skill to ensure everything passes:

```bash
uv run ruff check claude_discord/
uv run ruff format claude_discord/
uv run pytest tests/ -v --cov=claude_discord
```

## Conventions

- **Type hints**: Required on all function signatures
- **`from __future__ import annotations`**: Required in every file
- **Logging**: Use `logger = logging.getLogger(__name__)`, never `print()`
- **Authorization**: If the Cog accepts user commands, check `_is_authorized(user_id)`
- **Input validation**: Validate all user-provided strings with regex before passing to subprocess
- **Error handling**: Use `contextlib.suppress(discord.HTTPException)` for non-critical Discord API calls
