# Dead Code Analysis — claude-code-discord-bridge

Date: 2026-02-21  
Tools: vulture 2.14, ruff 0.15.2, coverage 7.6  
Total tests: 505 passing | Coverage: 80%

---

## Summary

| Category | Count | Action |
|----------|-------|--------|
| TRUE DEAD CODE (SAFE to delete) | 2 | Delete |
| FORMER FEATURE (CAUTION) | 1 | Delete + remove tests |
| FALSE POSITIVES (keep) | 30+ | No action |

---

## SAFE — Delete immediately

### 1. `AskAnswerBus.has_waiter()` — ask_bus.py:62

```python
def has_waiter(self, thread_id: int) -> bool:
    """Return True if a coroutine is currently waiting for this thread."""
    return thread_id in self._waiters
```

- **Zero callers** in production code and tests
- Coverage: ask_bus.py is only 46% covered — this is part of the dead half
- Safe to remove: only internal `_waiters` dict access, no external contract

### 2. `PendingAskRepository.update_question_idx()` — ask_repo.py:85

```python
async def update_question_idx(self, thread_id: int, question_idx: int) -> None:
    """Advance the current question index (called when moving to next question)."""
```

- **Zero callers** — designed for multi-question Ask flow that was never fully implemented
- ask_repo.py is only 50% covered overall
- Safe to remove: no tests, no callers

---

## CAUTION — Former feature, replaced by AI Lounge

### 3. `CoordinationService.post_session_start()` — coordination/service.py:51

```python
async def post_session_start(self, thread: discord.Thread, prompt_preview: str) -> None:
    """Post a session-started notice to the coordination channel."""
```

- **Zero production callers** — the call in `claude_chat.py` was removed when AI Lounge
  replaced the mechanical session-start post
- `post_session_end()` is still used — KEEP that one
- Tests for `post_session_start` exist in `test_coordination.py` but test dead functionality
- Action: delete method + delete corresponding tests

---

## FALSE POSITIVES (do NOT touch)

| Item | Reason |
|------|--------|
| `on_message`, `on_ready` event handlers | discord.py dynamic dispatch |
| `cog_load`, `cog_unload`, `_before_master_loop` | discord.py Cog lifecycle hooks |
| `stop_session`, `clear_session`, `sync_settings`, `run_skill` etc. | Slash commands (dynamic registration) |
| `row_factory` attributes | aiosqlite Connection property |
| `message_content`, `guilds` (Intents) | discord.py attribute assignment |
| `mark_sent`, `mark_failed` | Used in tests, public API |
| `_db_execute` | Used in tests (setup helper) |
| `list_active` | Used in tests |
| `ApiServer` class | Imported by discord-bot consumer |
| `created_at` dataclass fields | Data fields, not dead code |
| `utils/logger.py` | Used by main.py (0% coverage = main.py untested) |

---

## Coverage gaps (not dead code, but worth noting)

These files have low coverage due to Discord API dependency — they work but can't easily
be unit-tested. Not deletion candidates, but document the testing boundary:

| File | Coverage | Reason |
|------|----------|--------|
| bot.py | 0% | Discord connection code |
| main.py | 0% | Entry point |
| discord_ui/ask_view.py | 26% | Discord interaction UI |
| discord_ui/status.py | 34% | Discord emoji reactions |
| discord_ui/ask_bus.py | 46% | Ask feature (partially dead) |

