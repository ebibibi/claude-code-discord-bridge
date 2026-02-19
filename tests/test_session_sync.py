"""Tests for session sync features: schema migration, repository extensions, and CLI sync."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_discord.database.models import init_db
from claude_discord.database.repository import SessionRepository
from claude_discord.session_sync import CliSession, extract_recent_messages, scan_cli_sessions


@pytest.fixture
async def repo(tmp_path):
    """Create a repository backed by a temporary database."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return SessionRepository(db_path)


class TestSessionRecordOriginAndSummary:
    """Test that the sessions table supports origin and summary columns."""

    async def test_save_with_origin(self, repo):
        record = await repo.save(thread_id=1000, session_id="sess-1", origin="cli")
        assert record.origin == "cli"

    async def test_default_origin_is_discord(self, repo):
        record = await repo.save(thread_id=1001, session_id="sess-2")
        assert record.origin == "discord"

    async def test_save_with_summary(self, repo):
        record = await repo.save(thread_id=1002, session_id="sess-3", summary="Fix auth bug")
        assert record.summary == "Fix auth bug"

    async def test_summary_defaults_to_none(self, repo):
        record = await repo.save(thread_id=1003, session_id="sess-4")
        assert record.summary is None


class TestGetBySessionId:
    """Test reverse lookup: session_id → SessionRecord."""

    async def test_get_by_session_id(self, repo):
        await repo.save(thread_id=2000, session_id="abc-123")
        record = await repo.get_by_session_id("abc-123")
        assert record is not None
        assert record.thread_id == 2000

    async def test_get_by_session_id_not_found(self, repo):
        result = await repo.get_by_session_id("nonexistent")
        assert result is None


class TestListAll:
    """Test listing all sessions."""

    async def test_list_all_empty(self, repo):
        sessions = await repo.list_all()
        assert sessions == []

    async def test_list_all_returns_sessions(self, repo):
        await repo.save(thread_id=3000, session_id="sess-a", summary="First")
        await repo.save(thread_id=3001, session_id="sess-b", summary="Second")
        sessions = await repo.list_all()
        assert len(sessions) == 2

    async def test_list_all_ordered_by_last_used_desc(self, repo):
        await repo.save(thread_id=3100, session_id="old")
        await repo.save(thread_id=3101, session_id="new")
        sessions = await repo.list_all()
        # Most recent first
        assert sessions[0].session_id == "new"

    async def test_list_all_with_limit(self, repo):
        for i in range(5):
            await repo.save(thread_id=3200 + i, session_id=f"sess-{i}")
        sessions = await repo.list_all(limit=3)
        assert len(sessions) == 3


def _write_session_jsonl(path: Path, session_id: str, messages: list[dict]) -> None:
    """Helper to write a mock session JSONL file."""
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


class TestScanCliSessions:
    """Test scanning Claude Code CLI session files."""

    def test_scan_empty_dir(self, tmp_path):
        sessions = scan_cli_sessions(str(tmp_path))
        assert sessions == []

    def test_scan_single_session(self, tmp_path):
        session_id = "abc12345-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{session_id}.jsonl",
            session_id,
            [
                {
                    "type": "user",
                    "isMeta": True,
                    "sessionId": session_id,
                    "cwd": "/home/user",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "<command>clear</command>"},
                },
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": session_id,
                    "cwd": "/home/user/project",
                    "timestamp": "2026-02-19T10:00:01.000Z",
                    "message": {"role": "user", "content": "Fix the login bug"},
                },
            ],
        )
        sessions = scan_cli_sessions(str(tmp_path))
        assert len(sessions) == 1
        assert sessions[0].session_id == session_id
        assert sessions[0].summary == "Fix the login bug"
        assert sessions[0].working_dir == "/home/user/project"

    def test_scan_skips_meta_messages(self, tmp_path):
        session_id = "def12345-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{session_id}.jsonl",
            session_id,
            [
                {
                    "type": "user",
                    "isMeta": True,
                    "sessionId": session_id,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "meta stuff"},
                },
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": session_id,
                    "cwd": "/home/project",
                    "timestamp": "2026-02-19T10:01:00.000Z",
                    "message": {"role": "user", "content": "Real prompt here"},
                },
            ],
        )
        sessions = scan_cli_sessions(str(tmp_path))
        assert sessions[0].summary == "Real prompt here"

    def test_scan_handles_content_blocks_list(self, tmp_path):
        """Content can be a list of content blocks instead of a string."""
        session_id = "444ddddd-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{session_id}.jsonl",
            session_id,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": session_id,
                    "cwd": "/home/project",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Fix the login bug"},
                            {"type": "text", "text": " and add tests"},
                        ],
                    },
                },
            ],
        )
        sessions = scan_cli_sessions(str(tmp_path))
        assert len(sessions) == 1
        assert "Fix the login bug" in sessions[0].summary
        assert "add tests" in sessions[0].summary

    def test_scan_skips_xml_prefixed_content(self, tmp_path):
        session_id = "111aaaaa-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{session_id}.jsonl",
            session_id,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": session_id,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {
                        "role": "user",
                        "content": "<local-command-stdout>output</local-command-stdout>",
                    },
                },
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": session_id,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:01.000Z",
                    "message": {"role": "user", "content": "Actual user prompt"},
                },
            ],
        )
        sessions = scan_cli_sessions(str(tmp_path))
        assert sessions[0].summary == "Actual user prompt"

    def test_scan_truncates_long_summary(self, tmp_path):
        session_id = "222bbbbb-1234-5678-9abc-def012345678"
        long_text = "x" * 200
        _write_session_jsonl(
            tmp_path / f"{session_id}.jsonl",
            session_id,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": session_id,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": long_text},
                },
            ],
        )
        sessions = scan_cli_sessions(str(tmp_path))
        assert len(sessions[0].summary) <= 100

    def test_scan_multiple_projects(self, tmp_path):
        # Create two project directories
        proj1 = tmp_path / "-home-user-proj1"
        proj1.mkdir()
        proj2 = tmp_path / "-home-user-proj2"
        proj2.mkdir()

        sid1 = "aaa11111-1234-5678-9abc-def012345678"
        sid2 = "bbb22222-1234-5678-9abc-def012345678"

        _write_session_jsonl(
            proj1 / f"{sid1}.jsonl",
            sid1,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid1,
                    "cwd": "/home/user/proj1",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "Project 1 task"},
                },
            ],
        )
        _write_session_jsonl(
            proj2 / f"{sid2}.jsonl",
            sid2,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid2,
                    "cwd": "/home/user/proj2",
                    "timestamp": "2026-02-19T11:00:00.000Z",
                    "message": {"role": "user", "content": "Project 2 task"},
                },
            ],
        )

        sessions = scan_cli_sessions(str(tmp_path))
        assert len(sessions) == 2
        ids = {s.session_id for s in sessions}
        assert sid1 in ids
        assert sid2 in ids

    def test_scan_handles_malformed_jsonl(self, tmp_path):
        session_id = "333ccccc-1234-5678-9abc-def012345678"
        jsonl_path = tmp_path / f"{session_id}.jsonl"
        with open(jsonl_path, "w") as f:
            f.write("not valid json\n")
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "isMeta": False,
                        "sessionId": session_id,
                        "cwd": "/home",
                        "timestamp": "2026-02-19T10:00:00.000Z",
                        "message": {"role": "user", "content": "Valid line"},
                    }
                )
                + "\n"
            )
        sessions = scan_cli_sessions(str(tmp_path))
        assert len(sessions) == 1
        assert sessions[0].summary == "Valid line"

    def test_scan_respects_limit(self, tmp_path):
        """Only the newest N sessions should be returned when limit is set."""
        import os

        for i in range(5):
            sid = f"aaa{i:05d}-1234-5678-9abc-def012345678"
            path = tmp_path / f"{sid}.jsonl"
            _write_session_jsonl(
                path,
                sid,
                [
                    {
                        "type": "user",
                        "isMeta": False,
                        "sessionId": sid,
                        "cwd": "/home",
                        "timestamp": f"2026-02-19T1{i}:00:00.000Z",
                        "message": {"role": "user", "content": f"Task {i}"},
                    },
                ],
            )
            # Ensure distinct mtimes
            os.utime(path, (1000000 + i * 100, 1000000 + i * 100))

        sessions = scan_cli_sessions(str(tmp_path), limit=3)
        assert len(sessions) == 3

    def test_scan_limit_zero_returns_all(self, tmp_path):
        """limit=0 should return all sessions."""
        for i in range(5):
            sid = f"bbb{i:05d}-1234-5678-9abc-def012345678"
            _write_session_jsonl(
                tmp_path / f"{sid}.jsonl",
                sid,
                [
                    {
                        "type": "user",
                        "isMeta": False,
                        "sessionId": sid,
                        "cwd": "/home",
                        "timestamp": f"2026-02-19T1{i}:00:00.000Z",
                        "message": {"role": "user", "content": f"Task {i}"},
                    },
                ],
            )
        sessions = scan_cli_sessions(str(tmp_path), limit=0)
        assert len(sessions) == 5

    def test_scan_max_lines_stops_early(self, tmp_path):
        """If the user message is beyond max_lines, it should not be found."""
        sid = "ccc00000-1234-5678-9abc-def012345678"
        jsonl_path = tmp_path / f"{sid}.jsonl"
        # Write 25 assistant lines then one user line
        with open(jsonl_path, "w") as f:
            for i in range(25):
                f.write(
                    json.dumps(
                        {
                            "type": "assistant",
                            "sessionId": sid,
                            "timestamp": f"2026-02-19T10:00:{i:02d}.000Z",
                            "message": {"role": "assistant", "content": f"resp {i}"},
                        }
                    )
                    + "\n"
                )
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "isMeta": False,
                        "sessionId": sid,
                        "cwd": "/home",
                        "timestamp": "2026-02-19T10:01:00.000Z",
                        "message": {"role": "user", "content": "Late user message"},
                    }
                )
                + "\n"
            )
        # max_lines=5 should miss the user message at line 26
        sessions = scan_cli_sessions(str(tmp_path), max_lines_per_file=5)
        assert len(sessions) == 0

        # max_lines=30 should find it
        sessions = scan_cli_sessions(str(tmp_path), max_lines_per_file=30)
        assert len(sessions) == 1
        assert sessions[0].summary == "Late user message"

    def test_cli_session_dataclass(self):
        s = CliSession(
            session_id="test-id",
            working_dir="/home",
            summary="Test",
            timestamp="2026-02-19T10:00:00.000Z",
        )
        assert s.session_id == "test-id"
        assert s.working_dir == "/home"


class TestScanSinceDays:
    """Test the since_days filter on scan_cli_sessions."""

    def test_since_days_excludes_old_files(self, tmp_path):
        """Files older than since_days should be excluded."""
        import os
        import time

        # Recent file (today)
        recent_id = "aaa11111-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{recent_id}.jsonl",
            recent_id,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": recent_id,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "Recent session"},
                },
            ],
        )

        # Old file (10 days ago)
        old_id = "bbb22222-1234-5678-9abc-def012345678"
        old_path = tmp_path / f"{old_id}.jsonl"
        _write_session_jsonl(
            old_path,
            old_id,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": old_id,
                    "cwd": "/home",
                    "timestamp": "2026-02-09T10:00:00.000Z",
                    "message": {"role": "user", "content": "Old session"},
                },
            ],
        )
        # Set mtime to 10 days ago
        old_time = time.time() - (10 * 86400)
        os.utime(old_path, (old_time, old_time))

        sessions = scan_cli_sessions(str(tmp_path), since_days=3)
        assert len(sessions) == 1
        assert sessions[0].session_id == recent_id

    def test_since_days_zero_means_no_filter(self, tmp_path):
        """since_days=0 should not filter any files."""
        import os
        import time

        for i, sid in enumerate(
            ["ccc33333-1234-5678-9abc-def012345678", "ddd44444-1234-5678-9abc-def012345678"]
        ):
            path = tmp_path / f"{sid}.jsonl"
            _write_session_jsonl(
                path,
                sid,
                [
                    {
                        "type": "user",
                        "isMeta": False,
                        "sessionId": sid,
                        "cwd": "/home",
                        "timestamp": f"2026-02-0{i + 1}T10:00:00.000Z",
                        "message": {"role": "user", "content": f"Session {i}"},
                    },
                ],
            )
            if i == 1:
                old_time = time.time() - (30 * 86400)
                os.utime(path, (old_time, old_time))

        sessions = scan_cli_sessions(str(tmp_path), since_days=0)
        assert len(sessions) == 2

    def test_since_days_default_is_no_filter(self, tmp_path):
        """Default behavior (no since_days) should return all sessions."""
        import os
        import time

        sid = "eee55555-1234-5678-9abc-def012345678"
        path = tmp_path / f"{sid}.jsonl"
        _write_session_jsonl(
            path,
            sid,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-01-01T10:00:00.000Z",
                    "message": {"role": "user", "content": "Ancient session"},
                },
            ],
        )
        old_time = time.time() - (60 * 86400)
        os.utime(path, (old_time, old_time))

        sessions = scan_cli_sessions(str(tmp_path))
        assert len(sessions) == 1


def _create_sessions_with_ages(tmp_path, ages_hours: list[int]) -> list[str]:
    """Helper: create N session files with specified ages in hours.

    Returns list of session IDs ordered same as ages_hours.
    """
    import os
    import time

    now = time.time()
    sids: list[str] = []
    for i, age_h in enumerate(ages_hours):
        sid = f"aa{i:06d}-1234-5678-9abc-def012345678"
        path = tmp_path / f"{sid}.jsonl"
        _write_session_jsonl(
            path,
            sid,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": f"2026-02-19T{10 + i:02d}:00:00.000Z",
                    "message": {"role": "user", "content": f"Session aged {age_h}h"},
                },
            ],
        )
        mtime = now - (age_h * 3600)
        os.utime(path, (mtime, mtime))
        sids.append(sid)
    return sids


class TestTwoTierFiltering:
    """Test the two-tier filtering: since_hours primary, min_results fallback."""

    def test_all_within_hours_returned(self, tmp_path):
        """When many sessions are within since_hours, return all of them."""
        # 15 sessions all within 12 hours
        _create_sessions_with_ages(tmp_path, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
        sessions = scan_cli_sessions(str(tmp_path), since_hours=24, min_results=10)
        assert len(sessions) == 15

    def test_fewer_than_min_results_fills_up(self, tmp_path):
        """When fewer than min_results within since_hours, fill up from most recent."""
        # 3 within 24h, 7 older → should return 10
        ages = [1, 12, 20] + [48, 72, 96, 120, 144, 168, 192]
        _create_sessions_with_ages(tmp_path, ages)
        sessions = scan_cli_sessions(str(tmp_path), since_hours=24, min_results=10)
        assert len(sessions) == 10

    def test_zero_within_hours_returns_min_results(self, tmp_path):
        """When nothing within since_hours, return min_results most recent."""
        # All older than 48h
        ages = [49, 50, 72, 96, 120, 144, 168, 192, 216, 240, 264, 288]
        _create_sessions_with_ages(tmp_path, ages)
        sessions = scan_cli_sessions(str(tmp_path), since_hours=24, min_results=10)
        assert len(sessions) == 10

    def test_total_less_than_min_results(self, tmp_path):
        """When total files < min_results, return all available."""
        ages = [49, 50, 72]  # 3 files, all old
        _create_sessions_with_ages(tmp_path, ages)
        sessions = scan_cli_sessions(str(tmp_path), since_hours=24, min_results=10)
        assert len(sessions) == 3

    def test_since_hours_zero_disables_time_filter(self, tmp_path):
        """since_hours=0 should apply limit only, no time filter."""
        ages = [1, 48, 96, 144]
        _create_sessions_with_ages(tmp_path, ages)
        sessions = scan_cli_sessions(str(tmp_path), since_hours=0, min_results=0, limit=50)
        assert len(sessions) == 4

    def test_min_results_zero_means_strict_time_filter(self, tmp_path):
        """min_results=0 means only return sessions within since_hours."""
        ages = [1, 12, 48, 96]  # 2 within 24h, 2 old
        _create_sessions_with_ages(tmp_path, ages)
        sessions = scan_cli_sessions(str(tmp_path), since_hours=24, min_results=0)
        assert len(sessions) == 2

    def test_resumed_session_appears_as_recent(self, tmp_path):
        """A session file touched recently (resumed) should appear in results."""

        # Create an "old" session but touch it recently (simulating resume)
        sid = "aee00000-1234-5678-9abc-def012345678"
        path = tmp_path / f"{sid}.jsonl"
        _write_session_jsonl(
            path,
            sid,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-01-01T10:00:00.000Z",  # Old timestamp in content
                    "message": {"role": "user", "content": "Old session resumed"},
                },
            ],
        )
        # mtime is now (just created), so it's within 24h
        sessions = scan_cli_sessions(str(tmp_path), since_hours=24, min_results=10)
        assert len(sessions) == 1
        assert sessions[0].session_id == sid

    def test_backward_compat_since_days_still_works(self, tmp_path):
        """since_days parameter should still work for backward compatibility."""

        ages_hours = [1, 48, 96]  # 1h, 2 days, 4 days
        _create_sessions_with_ages(tmp_path, ages_hours)
        # since_days=1 should only include the 1h-old session
        sessions = scan_cli_sessions(str(tmp_path), since_days=1)
        assert len(sessions) == 1


class TestExtractRecentMessages:
    """Test extracting recent conversation messages from a session file."""

    def test_extract_basic(self, tmp_path):
        sid = "aaa00000-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{sid}.jsonl",
            sid,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "Hello"},
                },
                {
                    "type": "assistant",
                    "sessionId": sid,
                    "timestamp": "2026-02-19T10:00:01.000Z",
                    "message": {"role": "assistant", "content": "Hi there!"},
                },
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:02.000Z",
                    "message": {"role": "user", "content": "Fix the bug"},
                },
                {
                    "type": "assistant",
                    "sessionId": sid,
                    "timestamp": "2026-02-19T10:00:03.000Z",
                    "message": {"role": "assistant", "content": "Done!"},
                },
            ],
        )
        messages = extract_recent_messages(str(tmp_path), sid, count=4)
        assert len(messages) == 4
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"
        assert messages[2].role == "user"
        assert messages[2].content == "Fix the bug"
        assert messages[3].role == "assistant"
        assert messages[3].content == "Done!"

    def test_extract_returns_last_n(self, tmp_path):
        sid = "bbb00000-1234-5678-9abc-def012345678"
        messages_data = []
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            msg = {
                "type": role,
                "sessionId": sid,
                "timestamp": f"2026-02-19T10:00:{i:02d}.000Z",
                "message": {"role": role, "content": f"Message {i}"},
            }
            if role == "user":
                msg["isMeta"] = False
                msg["cwd"] = "/home"
            messages_data.append(msg)
        _write_session_jsonl(tmp_path / f"{sid}.jsonl", sid, messages_data)
        result = extract_recent_messages(str(tmp_path), sid, count=3)
        assert len(result) == 3
        assert result[0].content == "Message 7"
        assert result[1].content == "Message 8"
        assert result[2].content == "Message 9"

    def test_extract_truncates_long_content(self, tmp_path):
        sid = "ccc00000-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{sid}.jsonl",
            sid,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "x" * 500},
                },
            ],
        )
        result = extract_recent_messages(str(tmp_path), sid, count=5, max_content_len=50)
        assert len(result) == 1
        assert len(result[0].content) == 53  # 50 + "..."
        assert result[0].content.endswith("...")

    def test_extract_skips_meta_and_xml(self, tmp_path):
        sid = "ddd00000-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{sid}.jsonl",
            sid,
            [
                {
                    "type": "user",
                    "isMeta": True,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "meta stuff"},
                },
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:01.000Z",
                    "message": {"role": "user", "content": "<xml>internal</xml>"},
                },
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:02.000Z",
                    "message": {"role": "user", "content": "Real message"},
                },
            ],
        )
        result = extract_recent_messages(str(tmp_path), sid, count=10)
        assert len(result) == 1
        assert result[0].content == "Real message"

    def test_extract_not_found(self, tmp_path):
        result = extract_recent_messages(str(tmp_path), "nonexistent-id")
        assert result == []

    def test_extract_content_blocks(self, tmp_path):
        sid = "eee00000-1234-5678-9abc-def012345678"
        _write_session_jsonl(
            tmp_path / f"{sid}.jsonl",
            sid,
            [
                {
                    "type": "assistant",
                    "sessionId": sid,
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Here is the fix"},
                            {"type": "text", "text": " for your bug"},
                        ],
                    },
                },
            ],
        )
        result = extract_recent_messages(str(tmp_path), sid, count=5)
        assert len(result) == 1
        assert "fix" in result[0].content

    def test_extract_in_subdirectory(self, tmp_path):
        """Session file can be in a project subdirectory."""
        sid = "fff00000-1234-5678-9abc-def012345678"
        subdir = tmp_path / "-home-user-project"
        subdir.mkdir()
        _write_session_jsonl(
            subdir / f"{sid}.jsonl",
            sid,
            [
                {
                    "type": "user",
                    "isMeta": False,
                    "sessionId": sid,
                    "cwd": "/home",
                    "timestamp": "2026-02-19T10:00:00.000Z",
                    "message": {"role": "user", "content": "From subdir"},
                },
            ],
        )
        result = extract_recent_messages(str(tmp_path), sid, count=5)
        assert len(result) == 1
        assert result[0].content == "From subdir"
