"""Tests for SessionRepository.search() — keyword search and date filtering."""

from __future__ import annotations

import pytest

from claude_discord.database.models import init_db
from claude_discord.database.repository import SessionRepository


@pytest.fixture
async def repo(tmp_path):
    """Create a repository backed by a temporary database."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return SessionRepository(db_path)


async def _seed(repo: SessionRepository) -> None:
    """Insert several sessions for search tests."""
    await repo.save(
        thread_id=1,
        session_id="sess-aaa",
        summary="Fix login bug",
        working_dir="/home/user/webapp",
        origin="discord",
    )
    await repo.save(
        thread_id=2,
        session_id="sess-bbb",
        summary="Add dark mode feature",
        working_dir="/home/user/webapp",
        origin="discord",
    )
    await repo.save(
        thread_id=3,
        session_id="sess-ccc",
        summary="Deploy to production",
        working_dir="/home/user/infra",
        origin="cli",
    )
    await repo.save(
        thread_id=4,
        session_id="sess-ddd",
        summary="Refactor database layer",
        working_dir="/home/user/ccdb",
        origin="discord",
    )
    await repo.save(
        thread_id=5,
        session_id="sess-eee",
        summary=None,
        working_dir=None,
        origin="discord",
    )


class TestSearchByKeyword:
    async def test_search_matches_summary(self, repo):
        await _seed(repo)
        results = await repo.search(query="login")
        assert len(results) == 1
        assert results[0].summary == "Fix login bug"

    async def test_search_matches_working_dir(self, repo):
        await _seed(repo)
        results = await repo.search(query="infra")
        assert len(results) == 1
        assert results[0].working_dir == "/home/user/infra"

    async def test_search_case_insensitive(self, repo):
        await _seed(repo)
        results = await repo.search(query="DARK MODE")
        assert len(results) == 1
        assert "dark mode" in results[0].summary.lower()

    async def test_search_multiple_matches(self, repo):
        await _seed(repo)
        results = await repo.search(query="webapp")
        assert len(results) == 2

    async def test_search_no_match(self, repo):
        await _seed(repo)
        results = await repo.search(query="nonexistent")
        assert len(results) == 0

    async def test_search_empty_query_returns_all(self, repo):
        await _seed(repo)
        results = await repo.search(query="")
        assert len(results) == 5

    async def test_search_none_query_returns_all(self, repo):
        await _seed(repo)
        results = await repo.search(query=None)
        assert len(results) == 5


class TestSearchWithOriginFilter:
    async def test_filter_by_origin(self, repo):
        await _seed(repo)
        results = await repo.search(query="", origin="cli")
        assert len(results) == 1
        assert results[0].origin == "cli"

    async def test_combined_keyword_and_origin(self, repo):
        await _seed(repo)
        results = await repo.search(query="webapp", origin="discord")
        assert len(results) == 2


class TestSearchLimit:
    async def test_respects_limit(self, repo):
        await _seed(repo)
        results = await repo.search(query="", limit=2)
        assert len(results) == 2

    async def test_default_limit(self, repo):
        await _seed(repo)
        results = await repo.search(query="")
        assert len(results) <= 50


class TestSearchOrdering:
    async def test_ordered_by_last_used_desc(self, repo):
        await _seed(repo)
        results = await repo.search(query="")
        for i in range(len(results) - 1):
            assert results[i].last_used_at >= results[i + 1].last_used_at


class TestSearchByThreadIds:
    """Filter to specific thread IDs (for orphaned thread detection)."""

    async def test_filter_by_thread_ids(self, repo):
        await _seed(repo)
        results = await repo.search(query="", thread_ids=[1, 3])
        assert len(results) == 2
        assert {r.thread_id for r in results} == {1, 3}

    async def test_exclude_thread_ids(self, repo):
        await _seed(repo)
        results = await repo.search(query="", exclude_thread_ids=[1, 2, 3])
        assert len(results) == 2
        assert {r.thread_id for r in results} == {4, 5}

    async def test_combined_query_and_exclude(self, repo):
        await _seed(repo)
        results = await repo.search(query="webapp", exclude_thread_ids=[1])
        assert len(results) == 1
        assert results[0].thread_id == 2
