# Architecture

## Overview

claude-code-discord-bridge is a thin UI layer that bridges Discord messages to the Claude Code CLI. It has no AI logic of its own — all intelligence comes from Claude Code's existing capabilities (CLAUDE.md, skills, tools, memory, MCP servers). The bridge's sole responsibility is: accept user input from Discord, spawn the CLI, parse its output, and render results back to Discord.

```
┌─────────────────────────────────────────────────────────┐
│                    Discord (Gateway)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ Channel   │  │ Threads  │  │ Reactions / Embeds   │  │
│  └─────┬────┘  └────┬─────┘  └──────────┬───────────┘  │
└────────┼────────────┼───────────────────┼───────────────┘
         │            │                   ▲
         ▼            ▼                   │
┌─────────────────────────────────────────┼───────────────┐
│              discord.py Bot (bot.py)    │               │
│  ┌────────────────┐  ┌─────────────────┴──────┐        │
│  │ ClaudeChatCog  │  │ SkillCommandCog        │        │
│  │ (claude_chat)  │  │ (skill_command)        │        │
│  └───────┬────────┘  └───────┬────────────────┘        │
│          │                   │                          │
│          └─────────┬─────────┘                          │
│                    ▼                                    │
│          ┌─────────────────┐                            │
│          │ _run_helper.py  │  ← shared execution logic  │
│          └────────┬────────┘                            │
│                   │                                     │
│     ┌─────────────┼──────────────┐                      │
│     ▼             ▼              ▼                      │
│  ┌────────┐  ┌──────────┐  ┌──────────┐                │
│  │ runner │  │ status   │  │ chunker  │                │
│  │  .py   │  │  .py     │  │  .py     │                │
│  └───┬────┘  └──────────┘  └──────────┘                │
│      │                                                  │
│      ▼                                                  │
│  ┌──────────┐  ┌──────────────┐                         │
│  │ parser   │  │ repository   │                         │
│  │  .py     │  │  .py (SQLite)│                         │
│  └──────────┘  └──────────────┘                         │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              Claude Code CLI (subprocess)                │
│  claude -p --output-format stream-json --model sonnet   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ CLAUDE.md, skills, tools, memory, MCP servers   │    │
│  │ (all inherited from the host environment)       │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Module Responsibilities

### Entry Points

| Module | Role |
|--------|------|
| `main.py` | Standalone entry point. Loads `.env`, initializes DB, creates components, starts bot. For users who run this as their only bot. |
| `__init__.py` | Public API surface. Exports `ClaudeChatCog`, `ClaudeRunner`, `SessionRepository`, and all types needed by consumers who embed this into their own bot. |
| `bot.py` | `ClaudeDiscordBot` — minimal `commands.Bot` subclass. Configures intents (message_content, guilds), stores `channel_id`, syncs slash commands on ready. Only used in standalone mode. |

### Cogs Layer (`cogs/`)

| Module | Class | Role |
|--------|-------|------|
| `claude_chat.py` | `ClaudeChatCog` | Core message handler. Listens for `on_message` in the configured channel and its child threads. Creates threads for new conversations, resumes sessions for thread replies. Manages concurrency via `asyncio.Semaphore`. Provides `/clear` slash command to reset sessions. |
| `skill_command.py` | `SkillCommandCog` | Provides `/skill` and `/skills` slash commands. Scans `~/.claude/skills/` at startup, parses YAML frontmatter from `SKILL.md` files, offers Discord autocomplete. Creates a thread and delegates to `_run_helper`. |
| `_run_helper.py` | `run_claude_in_thread()` | Shared function extracted to avoid duplicating the Claude CLI streaming logic between ClaudeChatCog and SkillCommandCog. Handles the full event loop: session init, tool use embeds, status updates, text accumulation, chunked response posting, error handling, and session persistence. |

### Claude CLI Layer (`claude/`)

| Module | Class/Function | Role |
|--------|---------------|------|
| `runner.py` | `ClaudeRunner` | Subprocess lifecycle manager. Builds command args, sanitizes environment, spawns `claude` via `create_subprocess_exec`, reads stdout line-by-line, yields `StreamEvent` objects. Handles timeout, cleanup, and `kill()`. Supports `clone()` for creating fresh runner instances per session. |
| `parser.py` | `parse_line()` | Stateless JSON parser. Takes a single line of stream-json output, returns a `StreamEvent` or `None`. Dispatches to `_parse_system`, `_parse_assistant`, `_parse_user`, `_parse_result` based on message type. |
| `types.py` | `StreamEvent`, `ToolUseEvent`, `SessionState`, enums | Type definitions. `MessageType` (system/assistant/user/result), `ContentBlockType` (text/tool_use/tool_result), `ToolCategory` (read/edit/command/web/think/other). `TOOL_CATEGORIES` maps Claude Code tool names to categories. `ToolUseEvent.display_name` provides human-readable descriptions. |

### Database Layer (`database/`)

| Module | Class/Function | Role |
|--------|---------------|------|
| `models.py` | `init_db()` | Schema definition and initialization. Single `sessions` table with `thread_id` (PK), `session_id`, `working_dir`, `model`, timestamps. Uses `datetime('now', 'localtime')` for timestamps. |
| `repository.py` | `SessionRepository` | CRUD operations. `get()` by thread_id, `save()` with upsert, `delete()`, `cleanup_old()` for age-based cleanup. Each operation opens and closes its own `aiosqlite` connection (simple, no connection pooling). |

### Discord UI Layer (`discord_ui/`)

| Module | Class/Function | Role |
|--------|---------------|------|
| `status.py` | `StatusManager` | Emoji reaction manager. Shows one status emoji at a time on the user's original message. Debounced at 700ms to avoid rate limits. Includes stall detection: soft warning (hourglass) at 10s, hard warning at 30s. Maps `ToolCategory` to emoji. Cleans up reactions when done. |
| `chunker.py` | `chunk_message()` | Fence-aware message splitter. Splits at paragraph boundaries (preferred), then line boundaries, then hard-splits. Tracks open code fences and properly closes/reopens them across chunk boundaries. Limits chunks to 1950 chars (2000 minus overhead). |
| `embeds.py` | `tool_use_embed()`, `session_start_embed()`, etc. | Discord embed builders. Color-coded: blurple for info, green for success, red for error, yellow for tool use. Consistent visual language across all bot output. |

### Utilities (`utils/`)

| Module | Function | Role |
|--------|----------|------|
| `logger.py` | `setup_logging()` | Configures root logger with timestamp format. Silences discord.py's verbose logging (`WARNING` level). |

## Data Flow

### New Conversation

```
1. User sends message in configured channel
   │
2. on_message() in ClaudeChatCog
   │
3. _handle_new_conversation()
   ├── Create Discord thread (name = first 100 chars of message)
   │
4. _run_claude()
   ├── Check semaphore (post "waiting" if full)
   ├── Create StatusManager on user's message
   ├── Clone runner (fresh subprocess state)
   │
5. run_claude_in_thread()
   ├── Create SessionState
   │
6. runner.run(prompt, session_id=None)
   ├── _build_args() → [claude, -p, --output-format, stream-json, ...]
   ├── _build_env() → strip DISCORD_BOT_TOKEN etc.
   ├── create_subprocess_exec()
   │
7. Stream events:
   ├── SYSTEM {session_id} → save to DB, post session_start_embed
   ├── ASSISTANT {text}    → accumulate in SessionState
   ├── ASSISTANT {tool_use} → set status emoji, post tool_use_embed
   ├── USER {tool_result}  → set thinking emoji
   ├── RESULT {text, cost} → post chunked text, session_complete_embed
   │
8. Cleanup
   ├── Kill subprocess
   ├── Clean up status reactions
   └── Return session_id
```

### Thread Reply (Session Resume)

```
1. User replies in existing thread
   │
2. on_message() → _handle_thread_reply()
   ├── repo.get(thread_id) → SessionRecord with session_id
   │
3. _run_claude(session_id=existing_id)
   │
4. runner.run(prompt, session_id=existing_id)
   ├── _build_args includes --resume {session_id}
   │
5. Same streaming flow as above
   └── Session ID persisted on RESULT event
```

### Skill Execution

```
1. User invokes /skill goodmorning
   │
2. SkillCommandCog.run_skill()
   ├── Validate skill name (regex)
   ├── Look up in loaded skills list
   ├── Defer interaction
   ├── Create thread named "/goodmorning"
   │
3. run_claude_in_thread(prompt="/goodmorning", session_id=None)
   │
4. Same streaming flow as new conversation
   └── Claude Code interprets "/goodmorning" as a skill invocation
```

## Concurrency Model

```
                    ┌──────────────────┐
                    │   Semaphore(N)   │  N = MAX_CONCURRENT_SESSIONS (default 3)
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
   │ Thread #1   │   │ Thread #2   │   │ Thread #3   │
   │ Runner (A)  │   │ Runner (B)  │   │ Runner (C)  │
   │ claude proc │   │ claude proc │   │ claude proc │
   └─────────────┘   └─────────────┘   └─────────────┘
```

- Each Claude CLI invocation gets its own `ClaudeRunner` instance via `clone()`.
- The `_active_runners` dict tracks runners by thread_id for kill-on-demand (`/clear`).
- The semaphore is held in `_run_helper.run_claude_with_config()` and applies to **all** code paths — chat, skills, scheduler, and webhooks. It is released in the `finally` block before compact/ask reruns to prevent deadlocks on recursive calls.
- Excess requests queue with a "waiting" message to prevent resource exhaustion.
- All I/O is async (asyncio subprocess, aiosqlite), so the event loop is never blocked.

## Extension Points

### For Framework Consumers (Package Users)

1. **Custom Cogs**: Import `ClaudeChatCog` and `SkillCommandCog`, add to your own `commands.Bot`. Add your own Cogs alongside them.
2. **Custom Runner Configuration**: `ClaudeRunner` accepts `command`, `model`, `permission_mode`, `working_dir`, `timeout_seconds`, `allowed_tools`, `dangerously_skip_permissions`.
3. **Selective Imports**: `__init__.py` exports individual components — use only what you need. Import `parse_line` and `chunk_message` for custom pipelines.
4. **run_claude_in_thread()**: Can be called from any Cog or async context. Needs a `Thread`, `ClaudeRunner`, `SessionRepository`, and a prompt.

### For Framework Contributors

1. **New Cog**: Follow CONTRIBUTING.md pattern. Use `_run_helper.run_claude_in_thread()` for Claude execution.
2. **New Tool Category**: Add to `ToolCategory` enum, update `TOOL_CATEGORIES` mapping in `types.py`, add emoji in `status.py` `CATEGORY_EMOJI` and `embeds.py` `CATEGORY_ICON`.
3. **New Event Type**: Add to `MessageType` enum, add `_parse_xxx()` function in `parser.py`, handle in `_run_helper.py` event loop.
4. **New Embed Type**: Add builder function in `embeds.py`, call from `_run_helper.py`.

## Dependency Graph

```
claude_discord/
  __init__.py ──────────┬──→ claude/runner.py
                        ├──→ claude/parser.py
                        ├──→ claude/types.py
                        ├──→ cogs/claude_chat.py ──→ _run_helper.py ──→ runner, types
                        ├──→ cogs/skill_command.py ──→ _run_helper.py     parser, repo
                        ├──→ database/repository.py                       status, chunker
                        ├──→ discord_ui/status.py                         embeds
                        ├──→ discord_ui/chunker.py
                        └──→ discord_ui/embeds.py

  main.py ──→ bot.py, runner, claude_chat, models, repository, logger

External:
  discord.py (Gateway, commands, app_commands)
  aiosqlite (async SQLite)
  python-dotenv (env loading, standalone mode only)
```

Key design constraint: `claude/` and `discord_ui/` have zero dependencies on each other. The `cogs/` layer (specifically `_run_helper.py`) is the only place where CLI output meets Discord rendering. This keeps the parser testable without Discord mocks and the UI components testable without subprocess mocks.
