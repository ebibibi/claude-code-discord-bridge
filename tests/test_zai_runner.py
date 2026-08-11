"""Tests for the Z.ai backend's provider-specific Claude Code environment."""

from __future__ import annotations

from pathlib import Path

from claude_code_core.runner import ClaudeRunner
from claude_code_core.zai_runner import ZAI_ANTHROPIC_BASE_URL, ZaiRunner


def test_zai_env_file_does_not_affect_claude(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / "zai.env"
    env_file.write_text(
        "ANTHROPIC_AUTH_TOKEN=zai-secret\nANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic\n"
    )
    monkeypatch.setenv("CCDB_ZAI_ENV_FILE", str(env_file))
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    zai_env = ZaiRunner(model="glm-5.2[1m]")._build_env()
    claude_env = ClaudeRunner(model="sonnet")._build_env()

    assert zai_env["ANTHROPIC_AUTH_TOKEN"] == "zai-secret"
    assert zai_env["ANTHROPIC_BASE_URL"] == ZAI_ANTHROPIC_BASE_URL
    assert "ANTHROPIC_AUTH_TOKEN" not in claude_env
    assert "ANTHROPIC_BASE_URL" not in claude_env
    assert "CCDB_ZAI_ENV_FILE" not in zai_env
    assert "CCDB_ZAI_ENV_FILE" not in claude_env


def test_zai_never_reuses_inherited_anthropic_credentials(monkeypatch) -> None:
    monkeypatch.delenv("CCDB_ZAI_ENV_FILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-api-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "anthropic-auth-token")

    env = ZaiRunner(model="glm-5.2[1m]")._build_env()

    assert env["ANTHROPIC_BASE_URL"] == ZAI_ANTHROPIC_BASE_URL
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_explicit_env_file_overrides_process_setting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    process_file = tmp_path / "process.env"
    process_file.write_text("ANTHROPIC_AUTH_TOKEN=wrong\n")
    explicit_file = tmp_path / "explicit.env"
    explicit_file.write_text("ANTHROPIC_AUTH_TOKEN=right\n")
    monkeypatch.setenv("CCDB_ZAI_ENV_FILE", str(process_file))

    env = ZaiRunner(model="glm-5.2[1m]", env_file=str(explicit_file))._build_env()

    assert env["ANTHROPIC_AUTH_TOKEN"] == "right"


def test_clone_preserves_zai_backend_and_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "zai.env"
    runner = ZaiRunner(model="glm-5.2[1m]", env_file=str(env_file), thread_id=1)

    cloned = runner.clone(thread_id=2, model="glm-4.7")

    assert isinstance(cloned, ZaiRunner)
    assert cloned.env_file == str(env_file)
    assert cloned.thread_id == 2
    assert cloned.model == "glm-4.7"


def test_describe_api_is_zai_without_env_file(monkeypatch) -> None:
    monkeypatch.delenv("CCDB_ZAI_ENV_FILE", raising=False)

    assert ZaiRunner(model="glm-5.2[1m]").describe_api() == "Z.ai"


def test_zai_runner_declares_zai_backend_name() -> None:
    """ZaiRunner must identify itself as 'zai' so settings/embeds route it correctly."""
    assert ZaiRunner(model="glm-5.2[1m]").backend_name == "zai"
    # The base runner stays 'claude' — the override is opt-in per subclass.
    assert ClaudeRunner(model="sonnet").backend_name == "claude"
