"""Tests for session sync features: schema migration, repository extensions, and CLI sync."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_discord.database.models import init_db
from claude_discord.database.repository import SessionRepository
from claude_discord.session_sync import CliSession, scan_cli_sessions


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
