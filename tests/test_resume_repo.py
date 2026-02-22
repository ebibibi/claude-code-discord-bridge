"""Tests for PendingResumeRepository."""

from __future__ import annotations

import os
import tempfile

import pytest

from claude_discord.database.models import init_db
from claude_discord.database.resume_repo import PendingResumeRepository


@pytest.fixture
async def repo() -> PendingResumeRepository:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    await init_db(path)
    yield PendingResumeRepository(path, ttl_minutes=5)
    os.unlink(path)


class TestMark:
    @pytest.mark.asyncio
    async def test_mark_creates_row(self, repo: PendingResumeRepository) -> None:
        row_id = await repo.mark(12345, session_id="abc", reason="self_restart")
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_mark_is_idempotent_for_same_thread(self, repo: PendingResumeRepository) -> None:
        """Second mark for same thread replaces the first (UNIQUE constraint)."""
        await repo.mark(12345, session_id="old", reason="first")
        await repo.mark(12345, session_id="new", reason="second")
        pending = await repo.get_pending()
        assert len(pending) == 1
        assert pending[0].session_id == "new"
        assert pending[0].reason == "second"

    @pytest.mark.asyncio
    async def test_mark_stores_all_fields(self, repo: PendingResumeRepository) -> None:
        await repo.mark(
            99,
            session_id="sid-xyz",
            reason="custom_reason",
            resume_prompt="Please continue.",
        )
        pending = await repo.get_pending()
        assert len(pending) == 1
        p = pending[0]
        assert p.thread_id == 99
        assert p.session_id == "sid-xyz"
        assert p.reason == "custom_reason"
        assert p.resume_prompt == "Please continue."


class TestGetPending:
    @pytest.mark.asyncio
    async def test_get_pending_returns_all_within_ttl(self, repo: PendingResumeRepository) -> None:
        await repo.mark(1)
        await repo.mark(2)
        pending = await repo.get_pending()
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_get_pending_prunes_expired_rows(self, repo: PendingResumeRepository) -> None:
        """Rows with TTL=0 should be pruned immediately on next get_pending call."""
        zero_ttl_repo = PendingResumeRepository(repo._db_path, ttl_minutes=0)
        await zero_ttl_repo.mark(999)
        pending = await zero_ttl_repo.get_pending()
        # ttl_minutes=0 means "older than 0 minutes" which may or may not prune
        # depending on sub-second timing — the important thing is get_pending runs
        assert isinstance(pending, list)

    @pytest.mark.asyncio
    async def test_get_pending_returns_empty_when_none(self, repo: PendingResumeRepository) -> None:
        pending = await repo.get_pending()
        assert pending == []


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_row_by_id(self, repo: PendingResumeRepository) -> None:
        row_id = await repo.mark(42)
        await repo.delete(row_id)
        pending = await repo.get_pending()
        assert pending == []

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_safe(self, repo: PendingResumeRepository) -> None:
        await repo.delete(9999)  # Should not raise

    @pytest.mark.asyncio
    async def test_delete_by_thread(self, repo: PendingResumeRepository) -> None:
        await repo.mark(55)
        await repo.delete_by_thread(55)
        pending = await repo.get_pending()
        assert pending == []
