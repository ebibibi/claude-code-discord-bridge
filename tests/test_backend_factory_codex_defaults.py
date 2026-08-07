"""Tests for BackendFactory Codex model/effort defaults.

Codex must defer to its own CLI config for the default model (so ccdb never
pins a stale version like gpt-5.4), and the Claude-oriented env ``effort`` must
not leak into Codex spawns (its valid levels differ).
"""

from __future__ import annotations

import pytest

from claude_code_core.codex_runner import CodexRunner
from claude_code_core.runner import ClaudeRunner
from claude_discord.backend_factory import (
    DEFAULT_MODEL,
    BackendFactory,
    parse_codex_model_profiles,
    usable_codex_model_profiles,
)


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


def test_parse_codex_model_profiles() -> None:
    assert parse_codex_model_profiles("fugu=fugu,fugu-ultra=fugu") == {
        "fugu": "fugu",
        "fugu-ultra": "fugu",
    }


def test_parse_codex_model_profiles_rejects_invalid_entry() -> None:
    with pytest.raises(ValueError, match="Invalid CCDB_CODEX_MODEL_PROFILES"):
        parse_codex_model_profiles("fugu-ultra")


def test_factory_selects_profile_for_mapped_codex_model() -> None:
    factory = _factory(codex_model_profiles={"fugu-ultra": "fugu"})

    runner = factory.build(backend="codex", model="fugu-ultra")

    assert isinstance(runner, CodexRunner)
    assert runner.profile == "fugu"


def test_factory_leaves_unmapped_codex_model_on_default_profile() -> None:
    factory = _factory(codex_model_profiles={"fugu-ultra": "fugu"})

    runner = factory.build(backend="codex", model="gpt-5.6-sol")

    assert isinstance(runner, CodexRunner)
    assert runner.profile is None


def _write_fugu_config(tmp_path) -> dict[str, str]:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        """
[model_providers.sakana]
env_key = "SAKANA_API_KEY"
base_url = "https://api.sakana.example/v1"
""".strip(),
        encoding="utf-8",
    )
    (codex_home / "fugu.config.toml").write_text(
        """
model_provider = "sakana"
model_catalog_json = "fugu.json"
""".strip(),
        encoding="utf-8",
    )
    (codex_home / "fugu.json").write_text(
        '{"models":[{"slug":"fugu"},{"slug":"fugu-ultra"}]}',
        encoding="utf-8",
    )
    return {
        "HOME": str(tmp_path),
        "CODEX_HOME": str(codex_home),
        "SAKANA_API_KEY": "configured",
    }


def test_usable_profiles_require_profile_catalog_and_credential(tmp_path) -> None:
    env = _write_fugu_config(tmp_path)
    profiles = {"fugu": "fugu", "fugu-ultra": "fugu"}

    assert usable_codex_model_profiles(profiles, env=env) == profiles


def test_usable_profiles_hide_models_without_provider_credential(tmp_path) -> None:
    env = _write_fugu_config(tmp_path)
    env.pop("SAKANA_API_KEY")

    assert usable_codex_model_profiles({"fugu-ultra": "fugu"}, env=env) == {}


def test_usable_profiles_hide_models_missing_from_catalog(tmp_path) -> None:
    env = _write_fugu_config(tmp_path)

    assert usable_codex_model_profiles({"fugu-preview": "fugu"}, env=env) == {}


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
