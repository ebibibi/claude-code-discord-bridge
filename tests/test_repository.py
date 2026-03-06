"""Tests for session repository."""

import pytest

from claude_discord.claude.types import RateLimitInfo
from claude_discord.database.models import init_db
from claude_discord.database.repository import SessionRepository, UsageStatsRepository


@pytest.fixture
async def repo(tmp_path):
    """Create a repository backed by a temporary database."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return SessionRepository(db_path)


class TestSessionRepository:
    async def test_save_and_get(self, repo):
        record = await repo.save(thread_id=12345, session_id="session-abc")
        assert record.thread_id == 12345
        assert record.session_id == "session-abc"

        fetched = await repo.get(12345)
        assert fetched is not None
        assert fetched.session_id == "session-abc"

    async def test_get_nonexistent(self, repo):
        result = await repo.get(99999)
        assert result is None

    async def test_save_updates_existing(self, repo):
        await repo.save(thread_id=100, session_id="first")
        await repo.save(thread_id=100, session_id="second")

        record = await repo.get(100)
        assert record.session_id == "second"

    async def test_save_with_metadata(self, repo):
        await repo.save(
            thread_id=200,
            session_id="sess-1",
            working_dir="/home/user/project",
            model="opus",
        )
        record = await repo.get(200)
        assert record.working_dir == "/home/user/project"
        assert record.model == "opus"

    async def test_delete(self, repo):
        await repo.save(thread_id=300, session_id="sess-to-delete")
        assert await repo.delete(300) is True
        assert await repo.get(300) is None

    async def test_delete_nonexistent(self, repo):
        assert await repo.delete(99999) is False

    async def test_cleanup_old(self, repo):
        # Create a session (it will be "now")
        await repo.save(thread_id=400, session_id="recent")

        # Cleanup with 0 days should delete everything
        deleted = await repo.cleanup_old(days=0)
        assert deleted == 1

    async def test_update_context_stats_saves_values(self, repo):
        """update_context_stats() persists context_window and context_used."""
        await repo.save(thread_id=500, session_id="ctx-session")
        await repo.update_context_stats(thread_id=500, context_window=200000, context_used=134000)

        record = await repo.get(500)
        assert record is not None
        assert record.context_window == 200000
        assert record.context_used == 134000

    async def test_update_context_stats_noop_for_missing_session(self, repo):
        """update_context_stats() silently ignores unknown thread IDs."""
        # Should not raise even if the thread has no session row
        await repo.update_context_stats(thread_id=99999, context_window=200000, context_used=10000)

    async def test_context_stats_none_by_default(self, repo):
        """Newly saved sessions have NULL context stats."""
        await repo.save(thread_id=600, session_id="no-ctx")
        record = await repo.get(600)
        assert record is not None
        assert record.context_window is None
        assert record.context_used is None


@pytest.fixture
async def usage_repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return UsageStatsRepository(db_path)


class TestUsageStatsRepository:
    async def test_upsert_and_get_latest(self, usage_repo):
        """Saving a RateLimitInfo and fetching it back returns the same values."""
        info = RateLimitInfo(
            rate_limit_type="five_hour",
            status="allowed",
            utilization=0.61,
            resets_at=1234567890,
        )
        await usage_repo.upsert(info)

        result = await usage_repo.get_latest()
        assert len(result) == 1
        assert result[0].rate_limit_type == "five_hour"
        assert result[0].utilization == pytest.approx(0.61)
        assert result[0].resets_at == 1234567890
        assert result[0].status == "allowed"

    async def test_upsert_overwrites_same_type(self, usage_repo):
        """A second upsert for the same rate_limit_type replaces the first."""
        first = RateLimitInfo(
            rate_limit_type="seven_day", status="allowed", utilization=0.2, resets_at=111
        )
        second = RateLimitInfo(
            rate_limit_type="seven_day", status="allowed_warning", utilization=0.85, resets_at=222
        )
        await usage_repo.upsert(first)
        await usage_repo.upsert(second)

        result = await usage_repo.get_latest()
        assert len(result) == 1
        assert result[0].utilization == pytest.approx(0.85)
        assert result[0].resets_at == 222

    async def test_multiple_types_stored_separately(self, usage_repo):
        """Different rate_limit_types coexist as separate rows."""
        await usage_repo.upsert(
            RateLimitInfo(
                rate_limit_type="five_hour", status="allowed", utilization=0.5, resets_at=1
            )
        )
        await usage_repo.upsert(
            RateLimitInfo(
                rate_limit_type="seven_day", status="allowed", utilization=0.3, resets_at=2
            )
        )

        result = await usage_repo.get_latest()
        types = {r.rate_limit_type for r in result}
        assert types == {"five_hour", "seven_day"}

    async def test_get_latest_empty(self, usage_repo):
        """get_latest() returns empty list when no data recorded yet."""
        result = await usage_repo.get_latest()
        assert result == []
