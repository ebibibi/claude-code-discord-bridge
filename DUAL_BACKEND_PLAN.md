# Dual Backend Plan

## Goal

Support both Claude Code and Codex in the same Discord bridge without forking the product into two separate bots.

The key constraint for v1 is to add dual-backend support with the smallest possible amount of churn:

- Keep the current Claude path working.
- Add a Codex path that is good enough for real sessions.
- Avoid a repo-wide rename or broad architectural rewrite.
- Store backend choice per thread/session so resume works correctly.

## V1 Scope

V1 should support:

- A configurable default backend: `claude` or `codex`.
- Backend selection per new thread/session.
- Backend persisted in the session DB.
- Resume using the same backend that created the session.
- Existing Claude behavior preserved.
- Codex sessions with a common-denominator UX:
  - start
  - resume
  - stop/interruption
  - final response
  - final error
  - file attachments if explicitly requested
- Provider-specific CLI resume info for supported sessions.

V1 should not try to support:

- Hot-switching the same live session from Claude to Codex or vice versa.
- Full Claude feature parity for Codex.
- Codex support for Claude-only storage helpers such as sync/rewind.
- A package rename away from `claude_discord`.

## Explicit Non-Goals For V1

These should be deferred to v2 unless implementation turns out to be trivial:

- Codex `/sync-sessions`
- Codex `/rewind`
- Codex `/fork`
- Codex inbox classification
- Codex auto thread rename
- Codex statusline integration
- Codex skill integration via the current `~/.claude/skills` path
- Shared session continuity across providers

## Current Findings

### Claude assumptions in the current codebase

The current implementation is tightly coupled to Claude in a few concentrated places:

- CLI invocation and args are Claude-specific in `claude_discord/claude/runner.py`.
- Stream parsing is Claude-specific in `claude_discord/claude/parser.py`.
- Shared execution types are named as Claude types in `claude_discord/claude/types.py`.
- The event loop consumes Claude-shaped events in `claude_discord/cogs/event_processor.py`.
- Bootstrapping only knows one runner in `claude_discord/main.py`.
- Many helper features assume `claude -p` or `~/.claude/...`.

This is good news. The coupling is real, but it is not spread evenly across the whole repo.

### Codex observations from the local machine

Local CLI version observed during planning:

- `codex-cli 0.118.0`

Useful commands already available locally:

- `codex exec --json`
- `codex exec resume --json`
- `codex resume`
- `codex fork`

Codex session storage observed locally:

- `~/.codex/sessions/YYYY/MM/DD/rollout-...jsonl`

Important difference from Claude:

- Claude stores simple conversation JSONL under `~/.claude/projects/...`.
- Codex stores a richer event log with records such as `session_meta`, `event_msg`, and `response_item`.

Implication:

- Resume is probably viable in v1.
- Sync/rewind should be deferred because they rely on Claude's on-disk format.

## Recommended V1 Architecture

### 1. Add a backend enum, not a repo-wide rename

Introduce a small generic backend layer while leaving existing names in place where possible.

Recommended additions:

- `BackendKind = Literal["claude", "codex"]` or an enum
- `AgentRunner` protocol with the small surface the shared cogs actually need

Recommended protocol shape:

```python
class AgentRunner(Protocol):
    command: str
    model: str
    working_dir: str | None
    dangerously_skip_permissions: bool

    def clone(...) -> "AgentRunner": ...
    async def run(self, prompt: str, session_id: str | None = None) -> AsyncGenerator[StreamEvent, None]: ...
    async def interrupt(self) -> None: ...
```

Do not rename the package, cogs, or exported public API in v1 unless needed for correctness.

### 2. Keep `session_id` as a provider-opaque handle

Do not rename the DB column in v1.

Instead:

- Add a new `backend` column to the `sessions` table.
- Keep `session_id` as the opaque resume handle for either provider.

Why:

- This minimizes migration work.
- Existing code paths already expect `session_id`.
- Claude IDs and Codex thread/session handles can both fit in the same column.

### 3. Use two concrete runners behind one shared execution path

Keep the current Claude runner mostly intact.

Add a new Codex runner that implements the same protocol:

- `claude_discord/claude/runner.py` stays as the Claude implementation.
- Add `claude_discord/codex/runner.py` as the Codex implementation.

The shared cogs should stop depending on `ClaudeRunner` directly and depend on `AgentRunner` instead.

### 4. Make Codex emit the existing shared `StreamEvent` type

Do not rewrite `EventProcessor` for Codex in v1.

Instead, make `CodexRunner.run()` translate Codex CLI behavior into the subset of `StreamEvent` needed by the current shared path:

- `SYSTEM` event with a provider-specific session handle
- `RESULT` event with final text
- `RESULT` event with final error when needed

In v1, Codex should not attempt to emit:

- partial assistant text
- tool use events
- tool result events
- permission requests
- elicitation requests
- todo events
- plan approval events
- compaction events

This keeps the Codex path intentionally thin.

### 5. Treat Claude-only prompt injection as optional

The current Claude path uses `--append-system-prompt`.

Codex CLI help did not show an equivalent flag in the local install used for planning.

For v1:

- Keep the existing Claude path unchanged.
- For Codex, do not try to replicate AI Lounge or compaction guardrails.
- If file attachment instructions are needed for Codex, prepend a minimal instruction block directly to the prompt rather than depending on Claude-only system-prompt injection.

## Backend Selection UX

Revised UX requirement:

- Existing message-based flow uses the configured default backend.
- The default backend must be changeable from Discord, not only from env/config.
- There must be a simpler Discord command to start a session on a specific backend.

Current shipped shape:

- Existing message-based flow uses the persisted default backend when present.
- The default backend can be shown/changed from Discord:
  - `/backend-show`
  - `/backend-set backend:{claude|codex}`
- Short explicit backend launch commands exist:
  - `/claude prompt:<text>`
  - `/codex prompt:<text>`
- The explicit generic command remains available:
  - `/session backend:{claude|codex} prompt:<text>`
- Operator env/config remains only the fallback source when no Discord setting is stored.

This satisfies the UX requirement that backend choice feel natural inside Discord.

Thread behavior in v1:

- Once a thread has a backend, future replies in that thread continue on that backend.
- Switching providers for an ongoing task means starting a new thread, not mutating the current session in place.

## Provider-Specific Feature Policy

### Supported in v1 for both

- New session
- Resume session
- Stop session
- Session list
- Resume info
- Final response/error rendering

### Claude-only in v1

- `/sync-sessions`
- `/rewind`
- `/fork`
- thread inbox classification
- thread auto rename
- statusline
- current skill loading path

Codex threads should either hide or clearly reject unsupported actions instead of failing implicitly.

## Implementation Phases

### Phase 1: DB and backend metadata

Files:

- `claude_discord/database/models.py`
- `claude_discord/database/repository.py`
- related tests

Tasks:

- Add `backend TEXT NOT NULL DEFAULT 'claude'` to the `sessions` table.
- Update `SessionRecord` and repository methods to read/write backend.
- Backfill existing rows to `claude`.
- Keep `session_id` untouched.

Acceptance criteria:

- Existing Claude sessions continue to load.
- New sessions persist backend.
- Resume lookup returns backend with the session record.

### Phase 2: Introduce a runner protocol and backend factory

Files:

- `claude_discord/protocols.py` or a new backend module
- `claude_discord/cogs/run_config.py`
- `claude_discord/cogs/claude_chat.py`
- `claude_discord/setup.py`
- `claude_discord/main.py`
- `claude_discord/discord_ui/views.py`

Tasks:

- Add `AgentRunner` protocol.
- Change shared cogs and views to depend on the protocol, not `ClaudeRunner`.
- Add backend-aware runner construction in bootstrap.
- Keep the current `ClaudeRunner` working through the new interface.

Acceptance criteria:

- The codebase still runs Claude unchanged after the abstraction lands.
- No Codex logic is required yet for this phase to pass.

### Phase 3: Add `CodexRunner`

Files:

- new `claude_discord/codex/runner.py`
- optional new `claude_discord/codex/__init__.py`
- tests for Codex runner

Recommended approach:

- Use `codex exec --json` for new sessions.
- Use `codex exec resume --json <session_id>` for resumed sessions.
- Capture the final assistant message via `--output-last-message` so the shared layer can post the final text even if live event translation stays minimal.
- Parse enough JSON events to extract:
  - session/thread handle from `thread.started`
  - terminal failure from `turn.failed` or top-level `error`

Important note:

- Claude validates session IDs in the runner today.
- That validation must stay provider-specific.
- Do not move Claude's session ID regex into shared code because Codex handles may differ.

Acceptance criteria:

- `CodexRunner.run()` yields a start event and a final result/error event.
- Resumed Codex sessions use `codex exec resume`.
- Interrupt maps cleanly to process termination.

### Phase 4: Wire backend selection through chat flows

Files:

- `claude_discord/cogs/claude_chat.py`
- `claude_discord/cogs/session_manage.py`
- `claude_discord/setup.py`
- command/help text

Tasks:

- Determine backend for a new thread:
  - explicit `/session` command wins
  - otherwise use default backend
- Persist backend when the session starts
- On thread reply, load session record and use the matching runner
- Make `/resume-info` provider-aware:
  - Claude: `claude --resume <id>`
  - Codex: `codex exec resume <id>`

Acceptance criteria:

- Two threads in the same bot can use different backends.
- Resume uses the right backend automatically.
- Resume info shows the right CLI command.

### Phase 5: Disable or gate unsupported Codex-only paths

Files:

- `claude_discord/cogs/session_manage.py`
- `claude_discord/cogs/skill_command.py`
- `claude_discord/session_sync.py`
- `claude_discord/claude/rewind.py`
- helper UIs that assume `claude -p`

Tasks:

- Guard unsupported commands when the session backend is `codex`.
- Keep unsupported Codex actions explicit and user-visible.
- Do not try to silently emulate Claude-only features.

Acceptance criteria:

- Unsupported Codex features fail clearly, not mysteriously.
- Claude behavior remains unchanged.

### Phase 6: Documentation and tests

Files:

- `README.md`
- `CONTRIBUTING.md` if needed
- `.env.example`
- tests

Tasks:

- Document backend configuration and the v1 feature matrix.
- Document that Claude is feature-complete and Codex is v1-minimal.
- Add regression tests for Claude and new tests for Codex backend selection.

## Test Plan

Add at least:

- DB migration test for `backend`
- repository read/write test for mixed backend sessions
- Claude regression test proving existing `ClaudeRunner` still works
- Codex runner arg-building test for:
  - new session
  - resumed session
  - output-last-message path
- chat flow test that replies resume on the stored backend
- `/resume-info` test for both providers
- unsupported Codex feature guard tests

## Recommended File Touch List

Likely first-wave files:

- `claude_discord/database/models.py`
- `claude_discord/database/repository.py`
- `claude_discord/protocols.py`
- `claude_discord/cogs/run_config.py`
- `claude_discord/cogs/claude_chat.py`
- `claude_discord/cogs/session_manage.py`
- `claude_discord/main.py`
- `claude_discord/setup.py`
- `claude_discord/discord_ui/views.py`
- `claude_discord/claude/runner.py`
- new `claude_discord/codex/runner.py`
- `README.md`
- `.env.example`

## Open Questions To Resolve During Execution

These should be answered with a small spike, not with speculation:

1. Is the `thread.started.thread_id` value from `codex exec --json` the correct stable handle to persist and pass back into `codex exec resume`?
2. Does `--output-last-message` always produce the final assistant text for resumed sessions too?
3. What is the safest useful Codex execution mode for the bridge in practice:
   - `--full-auto`
   - stricter sandbox plus default config
   - config overrides via `-c`
4. Can Codex handle prepended bridge instructions cleanly enough for file attachment delivery without a true system-prompt flag?

## Recommended First Execution Session

When resuming this work in another session, start here:

1. Implement Phase 1 and Phase 2 only.
2. Get Claude green again after the abstraction.
3. Add `CodexRunner` with only start/result/error support.
4. Wire backend selection and resume.
5. Leave every Codex helper feature disabled until the core path works.

## Definition of Done for V1

V1 is done when all of the following are true:

- The bot can run Claude and Codex sessions from the same deployment.
- Backend is persisted per thread/session.
- Replying in a thread resumes with the same backend automatically.
- Claude remains backward compatible.
- Codex can complete real sessions with final output and errors rendered in Discord.
- Unsupported Codex extras are explicitly gated instead of broken.
