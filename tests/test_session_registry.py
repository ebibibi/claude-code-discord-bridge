"""Tests for the active session registry (Layer 2 of concurrency awareness)."""

from __future__ import annotations

from claude_discord.concurrency import ActiveSession, SessionRegistry


class TestSessionRegistry:
    """Core registry operations."""

    def test_register_and_list(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "Working on ccdb Issue #52", "/home/ebi/ccdb")
        sessions = registry.list_active()
        assert len(sessions) == 1
        assert sessions[0].thread_id == 1001
        assert sessions[0].description == "Working on ccdb Issue #52"
        assert sessions[0].working_dir == "/home/ebi/ccdb"

    def test_unregister(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "task A")
        registry.unregister(1001)
        assert registry.list_active() == []

    def test_unregister_nonexistent_is_noop(self) -> None:
        registry = SessionRegistry()
        registry.unregister(9999)  # Should not raise

    def test_multiple_sessions(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "task A", "/home/ebi/repo-a")
        registry.register(1002, "task B", "/home/ebi/repo-b")
        registry.register(1003, "task C")
        assert len(registry.list_active()) == 3

    def test_list_others_excludes_self(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "task A", "/home/ebi/repo-a")
        registry.register(1002, "task B", "/home/ebi/repo-b")
        others = registry.list_others(1001)
        assert len(others) == 1
        assert others[0].thread_id == 1002

    def test_list_others_empty_when_alone(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "task A")
        assert registry.list_others(1001) == []

    def test_update_description(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "initial task")
        registry.update(1001, description="updated task")
        sessions = registry.list_active()
        assert sessions[0].description == "updated task"

    def test_update_working_dir(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "task A")
        registry.update(1001, working_dir="/home/ebi/new-repo")
        sessions = registry.list_active()
        assert sessions[0].working_dir == "/home/ebi/new-repo"

    def test_update_nonexistent_is_noop(self) -> None:
        registry = SessionRegistry()
        registry.update(9999, description="nope")  # Should not raise

    def test_re_register_overwrites(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "old task")
        registry.register(1001, "new task")
        sessions = registry.list_active()
        assert len(sessions) == 1
        assert sessions[0].description == "new task"


class TestActiveSession:
    """ActiveSession data class."""

    def test_default_working_dir_is_none(self) -> None:
        session = ActiveSession(thread_id=1, description="test")
        assert session.working_dir is None

    def test_fields(self) -> None:
        session = ActiveSession(
            thread_id=42,
            description="fixing bug",
            working_dir="/tmp/repo",
        )
        assert session.thread_id == 42
        assert session.description == "fixing bug"
        assert session.working_dir == "/tmp/repo"


class TestConcurrencyNotice:
    """Tests for building the concurrency context string."""

    def test_no_others_returns_base_notice_only(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "my task")
        notice = registry.build_concurrency_notice(1001)
        assert "concurrency notice" in notice.lower()
        # Should NOT list specific other sessions
        assert "ACTIVE SESSIONS RIGHT NOW" not in notice

    def test_with_others_includes_session_info(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "task A", "/home/ebi/repo-a")
        registry.register(1002, "task B", "/home/ebi/repo-b")
        notice = registry.build_concurrency_notice(1001)
        assert "task B" in notice
        assert "repo-b" in notice

    def test_with_multiple_others(self) -> None:
        registry = SessionRegistry()
        registry.register(1001, "my task")
        registry.register(1002, "task B", "/home/ebi/repo-b")
        registry.register(1003, "task C", "/home/ebi/repo-c")
        notice = registry.build_concurrency_notice(1001)
        assert "task B" in notice
        assert "task C" in notice

    def test_notice_mentions_git_worktree(self) -> None:
        """The notice should advise git worktree usage."""
        registry = SessionRegistry()
        registry.register(1001, "my task")
        notice = registry.build_concurrency_notice(1001)
        assert "worktree" in notice.lower()

    def test_notice_mentions_shared_resources(self) -> None:
        """The notice should warn about non-git conflicts too."""
        registry = SessionRegistry()
        registry.register(1001, "my task")
        notice = registry.build_concurrency_notice(1001)
        # Should mention files, ports, or processes
        assert any(word in notice.lower() for word in ["file", "port", "process", "resource"])

    def test_notice_includes_own_thread_id(self) -> None:
        """The notice should identify the current session's thread ID.

        After context compaction the AI loses awareness of its own identity.
        The concurrency notice must explicitly state the thread ID so the AI
        can distinguish its own earlier lounge posts from other sessions'.
        """
        registry = SessionRegistry()
        registry.register(1001, "my task")
        notice = registry.build_concurrency_notice(1001)
        assert "1001" in notice
        assert "thread" in notice.lower()

    def test_notice_includes_this_thread_guidance(self) -> None:
        """The notice should explain that [this thread] markers are self-posts."""
        registry = SessionRegistry()
        registry.register(1001, "my task")
        notice = registry.build_concurrency_notice(1001)
        assert "[this thread]" in notice
