# Dual Backend Handoff

This document supplements `DUAL_BACKEND_PLAN.md`.

`DUAL_BACKEND_PLAN.md` remains the strategy document.
This file is the execution handoff: what has actually landed, what still
remains, and what should happen next.

## Current Verdict

The core P0 chat path is now backend-aware.

Important:

- Backend persistence exists.
- A minimal `CodexRunner` exists.
- Shared code now has a backend/runner abstraction.
- New sessions can now start on either `claude` or `codex`.
- Thread replies now choose the runner from the stored session backend.
- Startup resume now chooses the runner from the stored session backend.

The repo is still not fully dual-backend complete.

What remains is mostly:

- gating unsupported Codex commands/features
- suppressing Claude-only helper behavior on Codex runs
- deciding whether non-chat runner consumers should stay Claude-only or become backend-aware
- documentation/config cleanup

## What Was Implemented

### 1. Backend metadata is now stored in the session DB

Implemented:

- `sessions.backend TEXT NOT NULL DEFAULT 'claude'`
- migration/backfill for legacy rows
- `SessionRecord.backend`
- `SessionRepository.save(..., backend=...)`

Files:

- `claude_discord/database/models.py`
- `claude_discord/database/repository.py`

Result:

- Existing rows are treated as `claude`
- New rows can persist `claude` or `codex`

### 2. Shared backend primitives were added

Implemented:

- `BackendKind`
- `DEFAULT_BACKEND`
- `normalize_backend()`
- `build_resume_command()`

File:

- `claude_discord/backends.py`

Result:

- shared code can refer to backends without hardcoding Claude everywhere
- `/resume-info` can render the correct provider-specific resume command

### 3. Runner abstraction was introduced

Implemented:

- `AgentRunner` protocol
- shared type signatures updated from `ClaudeRunner` to `AgentRunner` in the key seams

Files:

- `claude_discord/protocols.py`
- `claude_discord/cogs/run_config.py`
- `claude_discord/discord_ui/views.py`
- `claude_discord/cogs/skill_command.py`
- `claude_discord/cogs/scheduler.py`
- `claude_discord/cogs/webhook_trigger.py`
- `claude_discord/setup.py`

Result:

- the codebase no longer requires every backend-aware seam to name `ClaudeRunner` directly
- Claude still fits the protocol
- Codex now also fits the protocol

### 4. Run config and event persistence are backend-aware

Implemented:

- `RunConfig.backend`
- `EventProcessor` saves `backend` when persisting session records

Files:

- `claude_discord/cogs/run_config.py`
- `claude_discord/cogs/event_processor.py`

Result:

- once a run is started with a backend, that backend can be saved with the session row

### 5. Provider-aware `/resume-info`

Implemented:

- Claude sessions show `claude --resume <id>`
- Codex sessions show `codex exec resume <id>`

File:

- `claude_discord/cogs/session_manage.py`

Result:

- persisted backend now affects a user-visible command

### 6. Minimal `CodexRunner` was added

Implemented:

- `claude_discord/codex/runner.py`
- export in `claude_discord/codex/__init__.py`
- export in `claude_discord/__init__.py`

Behavior:

- starts Codex with `codex exec --json`
- resumes with `codex exec resume --json`
- sends prompt via stdin
- supports `--output-last-message`
- translates:
  - `thread.started` -> shared `SYSTEM`
  - `turn.failed` -> shared terminal `RESULT` error
  - success -> shared terminal `RESULT` text

Notes:

- v1 implementation is intentionally thin
- no partial text streaming yet
- no tool/permission/elicitation translation yet
- `inject_tool_result()` is a no-op for Codex v1

Files:

- `claude_discord/codex/runner.py`
- `claude_discord/codex/__init__.py`

### 7. Backend-aware runner lookup and default backend wiring

Implemented:

- `ClaudeChatCog(..., runners=..., default_backend=...)`
- runner lookup via backend inside `ClaudeChatCog`
- `setup_bridge()` now builds a runner registry instead of assuming one concrete runner
- `setup_bridge()` auto-registers a builtin `CodexRunner`
- `CCDB_DEFAULT_BACKEND` env for message-based default backend

Files:

- `claude_discord/setup.py`
- `claude_discord/cogs/claude_chat.py`

Result:

- consumer code can keep calling `setup_bridge()` once
- the main chat path no longer needs custom wiring to reach Codex
- no repo-wide rename or invasive rewrite was needed

Note:

- `main.py` still instantiates only the base Claude runner directly, but this is
  no longer a blocker because `setup_bridge()` now creates/registers the Codex
  runner automatically

### 8. Real backend selection and backend-driven routing now exist for the main chat path

Implemented:

- explicit `/session backend:{claude|codex} prompt:<text>` command
- normal message-based new sessions use the configured default backend
- `_run_claude()` now clones the runner selected for that backend
- thread replies choose backend from `SessionRecord.backend`
- startup resume chooses backend from `SessionRecord.backend`
- startup resume also carries stored `working_dir` when available
- `/resume` now forwards `record.backend` into `spawn_session()`
- `/fork` now also forwards the stored backend into `spawn_session()`

Files:

- `claude_discord/cogs/claude_chat.py`
- `claude_discord/discord_ui/views.py`

Result:

- the core Discord chat lifecycle is now backend-correct end-to-end:
  - new session
  - session persistence
  - reply in thread
  - restart + resume

### 9. Regression coverage was added for the P0 routing slice

Added tests for:

- default-backend new sessions
- explicit `/session` backend override
- backend-aware thread replies
- backend-aware startup resume
- backend-aware `/resume` spawn path
- setup-time runner registry/default backend wiring
- programmatic `spawn_session()` using the configured default backend

Files:

- `tests/test_claude_chat.py`
- `tests/test_resume_command.py`
- `tests/test_setup.py`

Result:

- the new routing behavior now has targeted unit coverage

### 10. Discord backend-selection UX is now implemented

Implemented:

- persisted default backend stored in the shared `settings` table
- `/backend-show` to display the current default backend
- `/backend-set backend:{claude|codex}` to change the default backend from Discord
- short explicit launch commands:
  - `/claude prompt:<text>`
  - `/codex prompt:<text>`
- message-started new sessions and `spawn_session()` now resolve the default
  backend from settings first, then fall back to env/config
- existing `/session backend:{claude|codex} prompt:<text>` remains available

Files:

- `claude_discord/database/settings_repo.py`
- `claude_discord/cogs/session_manage.py`
- `claude_discord/cogs/claude_chat.py`
- `tests/test_settings_repo.py`
- `tests/test_session_manage.py`
- `tests/test_claude_chat.py`

Result:

- backend choice is now user-manageable from Discord instead of env-only
- env/config remains only the fallback boot-time source
- stored-backend reply/resume behavior stays unchanged

## Validation In This Session

Confirmed locally:

- `python3 -m compileall claude_discord/database/settings_repo.py claude_discord/cogs/session_manage.py claude_discord/cogs/claude_chat.py tests/test_settings_repo.py tests/test_session_manage.py tests/test_claude_chat.py`
- `git diff --check -- claude_discord/database/settings_repo.py claude_discord/cogs/session_manage.py claude_discord/cogs/claude_chat.py tests/test_settings_repo.py tests/test_session_manage.py tests/test_claude_chat.py`

Not run in this workspace:

- `pytest`
- `ruff`

Reason:

- this workspace did not have `uv`, `pytest`, or `ruff` available

## What Is Still Missing

### 1. Unsupported Codex-only commands still need gating

Still missing:

- `/rewind` guard for Codex
- `/fork` guard or real Codex fork semantics
- `/sync-sessions` guard/policy for Codex

Why this matters:

- `/rewind` still assumes Claude JSONL layout
- `/fork` now preserves backend correctly, but Codex does not yet implement the
  same semantics as Claude's fork flow in this code path
- `/sync-sessions` is still fundamentally Claude-storage-specific

### 2. Claude-only helper behavior still needs provider gating

Still missing:

- `EventProcessor` statusline/footer behavior is still Claude-oriented
- thread inbox classification still assumes the Claude-style helper path

Already improved:

- auto thread rename is now effectively limited to Claude-started sessions in the
  main message-start path

Why this matters:

- the main chat runner selection is fixed, but some post-processing still assumes
  Claude-specific surrounding features

### 3. Dual-backend support is still centered on the main chat path

Still missing or undecided:

- `SkillCommandCog` still uses a single runner
- `SchedulerCog` still uses a single runner
- `WebhookTriggerCog` still uses a single runner

Why this matters:

- the just-finished P0 slice fixed the human chat path first
- other runner consumers may need a later decision:
  - remain Claude-only in v1
  - or become backend-aware in a later slice

### 4. Docs/config cleanup still remains

Still missing:

- document the new backend-related env/config surface
- update operator-facing docs/examples as needed

Relevant config currently read in code:

- `CCDB_DEFAULT_BACKEND`
- `CODEX_COMMAND`
- `CODEX_MODEL`
- `CODEX_PERMISSION_MODE`
- `CODEX_WORKING_DIR`
- `CODEX_DANGEROUSLY_SKIP_PERMISSIONS`
- `CODEX_SANDBOX_MODE`

## P0 Status

The original P0 from the previous handoff is done for the main chat path.

Shipped:

- configurable default backend: `claude` or `codex`
- explicit new-session backend choice
- persistence of chosen backend at session start
- reply-in-thread uses stored backend automatically
- startup resume uses stored backend automatically

This was the required blocker before doing any other Codex feature work.

Important:

- the Discord UX for choosing/changing the backend is now in place
- follow-up work should focus on gating unsupported Codex-only behavior

## Recommended Next Implementation Order

### Step 1. Gate unsupported Codex commands first

Suggested files:

- `claude_discord/cogs/claude_chat.py`
- `claude_discord/cogs/session_manage.py`
- `claude_discord/cogs/session_sync.py`

Target behavior:

- Codex threads should get a clear "unsupported in v1" response for `/rewind`
- Codex threads should get a clear "unsupported in v1" response for `/fork`
- Codex-specific `/sync-sessions` should be blocked or hidden until explicitly designed

### Step 2. Gate Claude-only helper flows during Codex runs

Suggested files:

- `claude_discord/cogs/event_processor.py`

Target behavior:

- skip or replace Claude-only statusline/footer behavior for Codex
- skip or replace Claude-only inbox classification behavior for Codex

### Step 3. Decide the policy for non-chat runner consumers

Suggested files:

- `claude_discord/cogs/skill_command.py`
- `claude_discord/cogs/scheduler.py`
- `claude_discord/cogs/webhook_trigger.py`

Target decision:

- either explicitly keep them Claude-only for v1
- or add backend-aware runner lookup there in a later slice

### Step 4. Update docs/examples/config references

Suggested files:

- `README.md`
- `.env.example`
- any operator-facing docs that describe startup config

Target behavior:

- operators should know how to select a default backend
- operators should know how to configure the Codex runner
