"""Tests for the SessionBackend protocol and backend factory."""

from __future__ import annotations

import pytest

from claude_code_core.backend import SessionBackend, create_backend
from claude_code_core.runner import ClaudeRunner


class TestSessionBackendProtocol:
    """Verify that ClaudeRunner satisfies the SessionBackend protocol."""

    def test_claude_runner_is_session_backend(self) -> None:
        runner = ClaudeRunner(command="claude", model="sonnet")
        assert isinstance(runner, SessionBackend)

    def test_protocol_has_run_method(self) -> None:
        assert hasattr(SessionBackend, "run")

    def test_protocol_has_clone_method(self) -> None:
        assert hasattr(SessionBackend, "clone")

    def test_protocol_has_interrupt_method(self) -> None:
        assert hasattr(SessionBackend, "interrupt")

    def test_protocol_has_kill_method(self) -> None:
        assert hasattr(SessionBackend, "kill")

    def test_protocol_has_inject_tool_result_method(self) -> None:
        assert hasattr(SessionBackend, "inject_tool_result")

    def test_protocol_has_required_properties(self) -> None:
        runner = ClaudeRunner(command="claude", model="sonnet")
        assert hasattr(runner, "model")
        assert hasattr(runner, "working_dir")
        assert hasattr(runner, "permission_mode")
        assert hasattr(runner, "images")


class TestCreateBackend:
    """Tests for the backend factory function."""

    def test_default_creates_claude_runner(self) -> None:
        backend = create_backend(model="sonnet")
        assert isinstance(backend, ClaudeRunner)

    def test_claude_backend_explicit(self) -> None:
        backend = create_backend(backend="claude", model="sonnet")
        assert isinstance(backend, ClaudeRunner)

    def test_codex_backend(self) -> None:
        from claude_code_core.codex_runner import CodexRunner

        backend = create_backend(backend="codex", model="o4-mini")
        assert isinstance(backend, CodexRunner)

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown backend"):
            create_backend(backend="unknown", model="sonnet")

    def test_factory_passes_common_params(self) -> None:
        backend = create_backend(
            backend="claude",
            model="opus",
            working_dir="/tmp/test",
            timeout_seconds=600,
        )
        assert backend.model == "opus"
        assert backend.working_dir == "/tmp/test"
        assert backend.timeout_seconds == 600

    def test_codex_factory_params(self) -> None:
        from claude_code_core.codex_runner import CodexRunner

        backend = create_backend(
            backend="codex",
            model="o4-mini",
            working_dir="/tmp/test",
        )
        assert isinstance(backend, CodexRunner)
        assert backend.model == "o4-mini"
        assert backend.working_dir == "/tmp/test"
