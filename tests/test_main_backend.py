"""Tests for CCDB_BACKEND env var based backend selection in main.py."""

from __future__ import annotations

from claude_code_core.backend import create_backend
from claude_code_core.codex_runner import CodexRunner
from claude_code_core.runner import ClaudeRunner


class TestCreateBackendFromEnv:
    """Verify that create_backend() produces the right runner type."""

    def test_default_is_claude(self) -> None:
        backend = create_backend(model="sonnet")
        assert isinstance(backend, ClaudeRunner)

    def test_codex_backend(self) -> None:
        backend = create_backend(backend="codex", model="o4-mini")
        assert isinstance(backend, CodexRunner)

    def test_claude_backend_explicit(self) -> None:
        backend = create_backend(backend="claude", model="sonnet")
        assert isinstance(backend, ClaudeRunner)

    def test_codex_passes_working_dir(self) -> None:
        backend = create_backend(backend="codex", model="o4-mini", working_dir="/tmp")
        assert isinstance(backend, CodexRunner)
        assert backend.working_dir == "/tmp"

    def test_claude_passes_working_dir(self) -> None:
        backend = create_backend(backend="claude", model="sonnet", working_dir="/tmp")
        assert isinstance(backend, ClaudeRunner)
        assert backend.working_dir == "/tmp"
