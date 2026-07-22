"""Backend/session-store mismatch handling.

Regression tests for the "thread goes silent after a global /backend switch"
bug: the thread kept a Codex rollout ID while the active backend was Claude,
so every message spawned `claude --resume <codex-id>`, which exits instantly
with "No conversation found with session ID" and no user-visible output.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from claude_code_core.models import init_db
from claude_code_core.parser import parse_line
from claude_code_core.session_repo import SessionRepository
from claude_discord.backend_settings import session_is_resumable


class TestSessionIsResumable:
    def test_same_backend_is_resumable(self):
        assert session_is_resumable("codex", "codex") is True

    def test_cross_backend_is_not_resumable(self):
        assert session_is_resumable("codex", "claude") is False
        assert session_is_resumable("claude", "codex") is False

    def test_unknown_backend_assumes_compatible(self):
        """Records written before the backend column existed must keep working."""
        assert session_is_resumable(None, "claude") is True
        assert session_is_resumable("", "claude") is True


class TestSessionRepositoryBackendColumn:
    @pytest.mark.asyncio
    async def test_backend_roundtrip_and_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sessions.db")
            await init_db(db_path)
            repo = SessionRepository(db_path)

            await repo.save(1, "sess-a", working_dir="/w", backend="codex")
            assert (await repo.get(1)).backend == "codex"

            # A save without an explicit backend must not wipe the stored one.
            await repo.save(1, "sess-a2")
            record = await repo.get(1)
            assert record.backend == "codex"
            assert record.working_dir == "/w"

            # An explicit backend overwrites it.
            await repo.save(1, "sess-b", backend="claude")
            assert (await repo.get(1)).backend == "claude"

    @pytest.mark.asyncio
    async def test_backend_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sessions.db")
            await init_db(db_path)
            repo = SessionRepository(db_path)
            await repo.save(2, "sess-c")
            assert (await repo.get(2)).backend is None


class TestErrorDuringExecutionIsSurfaced:
    def test_resume_failure_becomes_event_error(self):
        """subtype=error_during_execution carries no `result` text — only errors[]."""
        line = (
            '{"type":"result","subtype":"error_during_execution","is_error":true,'
            '"duration_ms":0,"num_turns":0,"session_id":"019f7dfc-384f-7da2-8133-b73a5b44cd60",'
            '"errors":["No conversation found with session ID: '
            '019f7dfc-384f-7da2-8133-b73a5b44cd60"]}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.is_complete is True
        assert event.error is not None
        assert "No conversation found" in event.error

    def test_error_subtype_without_errors_array_still_reports(self):
        line = '{"type":"result","subtype":"error_max_turns","is_error":true}'
        event = parse_line(line)
        assert event is not None
        assert event.error is not None
        assert "error_max_turns" in event.error

    def test_successful_result_is_untouched(self):
        line = '{"type":"result","subtype":"success","is_error":false,"result":"done"}'
        event = parse_line(line)
        assert event is not None
        assert event.error is None
        assert event.text == "done"
