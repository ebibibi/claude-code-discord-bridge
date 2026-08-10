# EbiBot — Example Custom Bot using ccdb

Personal Discord bot built on top of [claude-code-discord-bridge](https://github.com/ebibibi/ebi-agent-chat-relay).

This example demonstrates how to extend ccdb with custom Cogs using the `CUSTOM_COGS_DIR` mechanism — no need for a separate repository.

## Custom Cogs

| Cog | File | Description |
|-----|------|-------------|
| ReminderCog | `cogs/reminder.py` | `/remind HH:MM "message"` slash command + 30s send loop |
| WatchdogCog | `cogs/watchdog.py` | Todoist overdue task monitor (30min check, daily dedup) |
| AutoUpgradeCog | `cogs/auto_upgrade.py` | Self-update via GitHub webhook + systemctl restart |
| DocsSyncCog | `cogs/docs_sync.py` | Auto-translate docs on push via webhook |
| AlertResponderCog | `cogs/alert_responder.py` | Watch a channel for ⚠️ alerts → auto-investigate with Claude Code |

## Quick Start

```bash
# 1. Clone and install ccdb
git clone https://github.com/ebibibi/ebi-agent-chat-relay.git
cd ebi-agent-chat-relay
uv sync

# 2. Copy and edit .env
cp examples/ebibot/.env.example .env
# Edit .env with your Discord bot token and channel IDs

# 3. Start with custom Cogs
ccdb start --cogs-dir examples/ebibot/cogs/

# Or via environment variable:
CUSTOM_COGS_DIR=examples/ebibot/cogs ccdb start
```

## How Custom Cogs Work

Each `.py` file in the cogs directory must expose a `setup()` function:

```python
async def setup(bot, runner, components):
    """Called by ccdb's custom Cog loader.

    Args:
        bot: discord.ext.commands.Bot instance
        runner: ClaudeRunner (Claude CLI invocation) — may be None
        components: BridgeComponents (session_repo, task_repo, etc.)
    """
    await bot.add_cog(MyCog(bot))
```

Files prefixed with `_` are skipped.  If one Cog fails to load, others still load normally.

## Architecture

```
ccdb (framework)
  |
  +-- setup_bridge() -> ClaudeChatCog, SessionManageCog, SkillCommandCog, SchedulerCog
  |
  +-- load_custom_cogs(cogs_dir) -> ReminderCog, WatchdogCog, AutoUpgradeCog, DocsSyncCog, AlertResponderCog
```

All Cogs share the same bot instance, event loop, and Discord connection.
