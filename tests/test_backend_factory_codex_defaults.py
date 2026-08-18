"""Tests for BackendFactory Codex model/effort defaults.

Codex must defer to its own CLI config for the default model (so ccdb never
pins a stale version like gpt-5.4), and the Claude-oriented env ``effort`` must
not leak into Codex spawns (its valid levels differ).
"""

from __future__ import annotations

from claude_code_core.codex_runner import CodexRunner
from claude_code_core.runner import ClaudeRunner
from claude_discord.backend_factory import DEFAULT_MODEL, BackendFactory


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


class TestCodexDefaultModel:
    def test_default_model_for_codex_is_none(self) -> None:
        assert DEFAULT_MODEL["codex"] is None
        assert _factory().default_model_for("codex") is None

    def test_default_model_for_claude_is_sonnet(self) -> None:
        assert _factory().default_model_for("claude") == "sonnet"

    def test_build_codex_without_model_defers_to_cli(self) -> None:
        runner = _factory().build(backend="codex")
        assert isinstance(runner, CodexRunner)
        # No --model passed → the CLI uses its config.toml default.
        assert runner.model is None
        assert "--model" not in runner._build_args("hi", session_id=None)

    def test_build_codex_with_explicit_model(self) -> None:
        runner = _factory().build(backend="codex", model="gpt-5.5")
        assert isinstance(runner, CodexRunner)
        assert runner.model == "gpt-5.5"


class TestEnvEffortDoesNotLeakToCodex:
    def test_env_effort_applies_to_claude(self) -> None:
        runner = _factory(effort="high").build(backend="claude")
        assert isinstance(runner, ClaudeRunner)
        assert runner.effort == "high"

    def test_env_effort_not_forwarded_to_codex(self) -> None:
        # The Claude-oriented env effort (which may be "max", invalid for Codex)
        # must not be applied to a Codex runner at build time.
        runner = _factory(effort="max").build(backend="codex")
        assert isinstance(runner, CodexRunner)
        assert runner.effort is None
