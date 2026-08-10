"""Backend/session-store mismatch handling.

Regression tests for the "thread goes silent after a global /backend switch"
bug: the thread kept a Codex rollout ID while the active backend was Claude,
so every message spawned `claude --resume <codex-id>`, which exits instantly
with "No conversation found with session ID" and no user-visible output.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_code_core.models import init_db
from claude_code_core.parser import parse_line
from claude_code_core.session_repo import SessionRepository
from claude_discord.backend_settings import session_is_resumable
from claude_discord.cogs.claude_chat import ClaudeChatCog
from claude_discord.database.repository import SessionRecord


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


class TestCrossBackendHandoffPreparation:
    @staticmethod
    def _record(*, backend: str = "claude") -> SessionRecord:
        return SessionRecord(
            thread_id=42,
            session_id="aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb",
            working_dir="/work",
            model=None,
            origin="discord",
            summary=None,
            created_at="",
            last_used_at="",
            backend=backend,
        )

    @staticmethod
    def _thread() -> MagicMock:
        thread = MagicMock(spec=discord.Thread)
        thread.id = 42
        thread.send = AsyncMock()
        return thread

    @staticmethod
    def _cog(record: SessionRecord, *, current_backend: str, transcript: str) -> ClaudeChatCog:
        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=record)
        settings = MagicMock()
        settings.current_backend = AsyncMock(return_value=current_backend)
        history = MagicMock()
        history.read.return_value = transcript
        runner = MagicMock()
        return ClaudeChatCog(
            bot=bot,
            repo=repo,
            runner=runner,
            backend_settings=settings,
            conversation_history=history,
        )

    async def test_mismatch_injects_file_transcript_and_starts_new_native_session(self) -> None:
        cog = self._cog(
            self._record(backend="claude"),
            current_backend="codex",
            transcript="User:\nold\n\nAssistant:\ndone",
        )

        session_id, prompt = await cog._prepare_cross_backend_handoff(
            self._thread(),
            "continue please",
            None,
        )

        assert session_id is None
        assert "Claude → Codex" in prompt
        assert "Assistant:\ndone" in prompt
        assert prompt.endswith("Current user message:\ncontinue please")
        cog._conversation_history.read.assert_called_once_with(
            "claude", "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
        )

    async def test_missing_file_degrades_to_fresh_session_with_original_prompt(self) -> None:
        cog = self._cog(
            self._record(backend="codex"),
            current_backend="claude",
            transcript="",
        )

        session_id, prompt = await cog._prepare_cross_backend_handoff(
            self._thread(),
            "current",
            None,
        )

        assert session_id is None
        assert prompt == "current"

    async def test_same_backend_keeps_native_resume_without_reading_file(self) -> None:
        record = self._record(backend="claude")
        cog = self._cog(record, current_backend="claude", transcript="unused")

        session_id, prompt = await cog._prepare_cross_backend_handoff(
            self._thread(),
            "current",
            record.session_id,
        )

        assert session_id == record.session_id
        assert prompt == "current"
        cog._conversation_history.read.assert_not_called()
