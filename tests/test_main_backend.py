"""Tests for CCDB_BACKEND env var based backend selection and env var renaming."""

from __future__ import annotations

from unittest.mock import patch

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


class TestEnvVarRename:
    """Verify CCDB_* env vars with CLAUDE_* fallbacks in load_config()."""

    _REQUIRED = {"DISCORD_BOT_TOKEN": "fake-token", "DISCORD_CHANNEL_ID": "12345"}

    def _load(self, env: dict[str, str]) -> dict[str, str]:
        from claude_discord.main import load_config

        merged = {**self._REQUIRED, **env}
        with patch.dict("os.environ", merged, clear=True):
            return load_config()

    def test_ccdb_model_takes_precedence(self) -> None:
        config = self._load({"CCDB_MODEL": "o4-mini", "CLAUDE_MODEL": "sonnet"})
        assert config["model"] == "o4-mini"

    def test_claude_model_fallback(self) -> None:
        config = self._load({"CLAUDE_MODEL": "opus"})
        assert config["model"] == "opus"

    def test_model_default(self) -> None:
        config = self._load({})
        assert config["model"] == "sonnet"

    def test_ccdb_command_takes_precedence(self) -> None:
        config = self._load({"CCDB_COMMAND": "codex", "CLAUDE_COMMAND": "claude"})
        assert config["command"] == "codex"

    def test_claude_command_fallback(self) -> None:
        config = self._load({"CLAUDE_COMMAND": "/usr/bin/claude"})
        assert config["command"] == "/usr/bin/claude"

    def test_ccdb_permission_mode_takes_precedence(self) -> None:
        config = self._load({"CCDB_PERMISSION_MODE": "auto", "CLAUDE_PERMISSION_MODE": "plan"})
        assert config["permission_mode"] == "auto"

    def test_ccdb_working_dir(self) -> None:
        config = self._load({"CCDB_WORKING_DIR": "/work"})
        assert config["working_dir"] == "/work"

    def test_claude_working_dir_fallback(self) -> None:
        config = self._load({"CLAUDE_WORKING_DIR": "/old"})
        assert config["working_dir"] == "/old"

    def test_ccdb_backend_env(self) -> None:
        config = self._load({"CCDB_BACKEND": "codex"})
        assert config["backend"] == "codex"
