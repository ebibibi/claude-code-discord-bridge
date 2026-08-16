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
| JobFailureTriageCog | `cogs/job_failure_triage.py` | Scheduler job failure embeds → auto-triage with Claude Code |
| ThreadCompletionCog | `cogs/thread_completion.py` | Thread deleted = work finished → file a record from the session transcript |

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
  +-- load_custom_cogs(cogs_dir) -> ReminderCog, WatchdogCog, AutoUpgradeCog, DocsSyncCog,
                                    AlertResponderCog, JobFailureTriageCog, ThreadCompletionCog
```

All Cogs share the same bot instance, event loop, and Discord connection.

## Thread Deletion as a Completion Signal

`ThreadCompletionCog` exists because this bot's owner uses Discord threads as a todo list and
deletes them when the work is done. That deletion is a completion label that costs nobody any
effort, so the Cog turns it into a written record.

The constraint that shapes the whole design: **by the time the delete event arrives, the thread's
messages are gone.** Nothing can be fetched back from Discord. The only material left is what ccdb
already held — the session row, and the transcript at
`~/.claude/projects/<project>/<session_id>.jsonl`, which contains every user turn, reply, and tool
call. That transcript is the primary source, so there is no need to mirror Discord separately.

Two consequences worth knowing before enabling it:

- **Deletions are batched.** Threads are usually cleaned up in bursts, so the Cog waits for a quiet
  period and then starts *one* session for the whole batch. Filing one session per deleted thread
  would create more threads than the cleanup removed.
- **Threads that never held a session are dropped.** Notification threads (scheduler alerts, PR
  watches) have no session row, and filing "work completed" for them would be a lie. The Cog's own
  record threads are ignored too, so deleting a record does not file a record about it.

**Where the record goes is not decided by the Cog.** Note-taking conventions — which file, which
folder, which headings — are personal, and this repository is public, so the Cog resolves the
deleted threads and hands over a manifest while the instructions live in an external template at
`THREAD_COMPLETION_PROMPT_FILE`. The template takes two placeholders:

| Placeholder | Expands to |
|-------------|------------|
| `{count}` | How many threads were deleted in this batch |
| `{manifest}` | Path to the JSON listing them, each with `summary` and `transcript_path` |

Leave it unset and a generic prompt is used, which says to record the work following the
workspace's own conventions without naming any. An unreadable path falls back to that same generic
prompt rather than dropping the batch — losing the wording is recoverable, losing the batch is not.

Configuration (the Cog is disabled unless the channel is set):

| Variable | Default | Purpose |
|----------|---------|---------|
| `THREAD_COMPLETION_CHANNEL_ID` | — (required) | Channel the record thread is created in |
| `THREAD_COMPLETION_DEBOUNCE` | `180` | Seconds of quiet before the batch is filed |
| `THREAD_COMPLETION_PROMPT_FILE` | — (generic prompt) | Template saying what to record and where |
