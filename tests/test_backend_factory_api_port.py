"""Tests for BackendFactory api_port / api_secret propagation.

Verifies that factory-built runners inherit api_port and api_secret so
CCDB_API_URL is injected into the subprocess environment.
"""

from __future__ import annotations

from claude_code_core.runner import ClaudeRunner
from claude_discord.backend_factory import BackendFactory


def _factory(**overrides: object) -> BackendFactory:
    defaults: dict[str, object] = {
        "claude_command": "claude",
        "codex_command": "codex",
        "permission_mode": "acceptEdits",
        "working_dir": None,
        "timeout_seconds": 300,
        "dangerously_skip_permissions": False,
        "allowed_tools": None,
        "append_system_prompt": None,
        "effort": None,
    }
    defaults.update(overrides)
    return BackendFactory(**defaults)  # type: ignore[arg-type]


class TestFactoryApiPort:
    def test_build_passes_api_port_to_runner(self) -> None:
        factory = _factory(api_port=8099)
        runner = factory.build(backend="claude")
        assert runner.api_port == 8099

    def test_build_passes_api_secret_to_runner(self) -> None:
        factory = _factory(api_port=8099, api_secret="s3cret")
        runner = factory.build(backend="claude")
        assert isinstance(runner, ClaudeRunner)
        assert runner.api_secret == "s3cret"

    def test_build_without_api_port_leaves_none(self) -> None:
        factory = _factory()
        runner = factory.build(backend="claude")
        assert runner.api_port is None

    def test_api_port_in_env(self) -> None:
        factory = _factory(api_port=8099)
        runner = factory.build(backend="claude")
        env = runner._build_env()
        assert env["CCDB_API_URL"] == "http://127.0.0.1:8099"

    def test_no_api_port_means_no_env_var(self) -> None:
        factory = _factory()
        runner = factory.build(backend="claude")
        env = runner._build_env()
        assert "CCDB_API_URL" not in env

    def test_api_port_set_after_init(self) -> None:
        """setup_bridge sets factory.api_port after construction."""
        factory = _factory()
        assert factory.api_port is None
        factory.api_port = 9090
        runner = factory.build(backend="claude")
        assert runner.api_port == 9090

    def test_codex_backend_also_gets_api_port(self) -> None:
        factory = _factory(api_port=8099)
        runner = factory.build(backend="codex")
        assert runner.api_port == 8099
        env = runner._build_env()
        assert env["CCDB_API_URL"] == "http://127.0.0.1:8099"
