"""Tests for the local-model backend.

The behaviour that matters here is not "does it spawn" but "does it refuse to
pretend". A local thread whose CLI still calls its vendor is worse than no
local mode at all, because the user believes something untrue.
"""

from __future__ import annotations

import pytest

from claude_code_core.backend import create_backend
from claude_code_core.local_backend import (
    DEFAULT_MODEL,
    PROVIDER_ID,
    LocalCodexRunner,
    LocalModelConfig,
    build_local_config_toml,
    ensure_codex_home,
    verify_quiet_settings,
)
from claude_code_core.types import MessageType, StreamEvent


@pytest.fixture
def local_config(tmp_path) -> LocalModelConfig:
    return LocalModelConfig(
        base_url="http://192.168.1.3:11434/v1",
        model="gpt-oss:120b",
        codex_home=tmp_path / "local-codex-home",
    )


class TestGeneratedConfig:
    def test_pins_the_local_provider_and_model(self, local_config):
        toml = build_local_config_toml(local_config)
        assert f'model_provider = "{PROVIDER_ID}"' in toml
        assert 'base_url = "http://192.168.1.3:11434/v1"' in toml
        assert 'model = "gpt-oss:120b"' in toml

    def test_requires_the_responses_wire_api(self, local_config):
        # codex-cli dropped `chat`; Ollama serves /v1/responses.
        assert 'wire_api = "responses"' in build_local_config_toml(local_config)

    def test_disables_both_measured_callers_home(self, local_config):
        toml = build_local_config_toml(local_config)
        assert "check_for_update_on_startup = false" in toml
        assert "[analytics]\nenabled = false" in toml

    def test_ensure_writes_the_file(self, local_config):
        home = ensure_codex_home(local_config)
        assert (home / "config.toml").is_file()
        assert verify_quiet_settings(home) == []

    def test_ensure_rewrites_a_tampered_file(self, local_config):
        home = ensure_codex_home(local_config)
        (home / "config.toml").write_text("model = 'something else'\n", encoding="utf-8")
        assert verify_quiet_settings(home)  # tampering is visible
        ensure_codex_home(local_config)
        assert verify_quiet_settings(home) == []  # and is undone

    def test_missing_file_reports_every_setting_missing(self, tmp_path):
        assert len(verify_quiet_settings(tmp_path / "absent")) == 2


class TestRunnerEnvironment:
    def test_points_the_cli_at_the_ccdb_owned_codex_home(self, local_config):
        runner = LocalCodexRunner(local_config=local_config)
        env = runner._build_env()
        assert env["CODEX_HOME"] == str(local_config.resolved_codex_home)

    def test_strips_cloud_credentials(self, local_config, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-survive")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        env = LocalCodexRunner(local_config=local_config)._build_env()
        assert "OPENAI_API_KEY" not in env
        assert "OPENAI_BASE_URL" not in env

    def test_refuses_to_run_when_the_quiet_settings_are_gone(self, local_config, monkeypatch):
        # Simulate a future CLI/config drift: the settings we rely on vanish.
        monkeypatch.setattr(
            "claude_code_core.local_backend.build_local_config_toml",
            lambda config: "model = 'x'\n",
        )
        runner = LocalCodexRunner(local_config=local_config)
        with pytest.raises(RuntimeError, match="Refusing to start the local backend"):
            runner._build_env()

    def test_describe_api_names_the_local_endpoint(self, local_config):
        assert "192.168.1.3" in LocalCodexRunner(local_config=local_config).describe_api()

    def test_clone_stays_local(self, local_config):
        clone = LocalCodexRunner(local_config=local_config).clone()
        assert isinstance(clone, LocalCodexRunner)
        assert clone.local_config is local_config


class TestModelSelection:
    """The selected model must have exactly one source: what /ollama use stored.

    An environment default used to shadow it. Because create_backend() passes
    ``model=None`` when nothing is stored, the runner omitted ``--model`` and
    fell back to config.toml — so `/ollama list` could report one model while
    the thread ran another.
    """

    def test_no_environment_variable_can_choose_the_model(self, monkeypatch):
        monkeypatch.setenv("CCDB_LOCAL_MODEL", "some-other-model:70b")
        assert LocalModelConfig.from_env().model == DEFAULT_MODEL

    def test_an_unset_model_still_reaches_the_cli_explicitly(self, local_config):
        runner = LocalCodexRunner(model=None, local_config=local_config)
        assert runner.model == local_config.model

    def test_a_stored_selection_wins(self, local_config):
        runner = LocalCodexRunner(model="qwen3.6:35b-a3b", local_config=local_config)
        assert runner.model == "qwen3.6:35b-a3b"


class TestTruncatedStream:
    """Ollama ends the stream without ``response.completed`` when its tool-call
    parser rejects the model's output. The CLI reports a transport error and
    retries the same context, so the turn dies with nothing the operator can act
    on unless ccdb names the cause."""

    @staticmethod
    async def _run(runner, events):
        async def fake_run(prompt, session_id=None):
            for event in events:
                yield event

        # Bypass CodexRunner.run(): the failure being described is what the CLI
        # reports, not how it is spawned.
        import claude_code_core.codex_runner as codex_runner

        original = codex_runner.CodexRunner.run
        codex_runner.CodexRunner.run = lambda self, prompt, session_id=None: fake_run(
            prompt, session_id
        )
        try:
            return [event async for event in runner.run("hi")]
        finally:
            codex_runner.CodexRunner.run = original

    async def test_explains_the_truncated_stream(self, local_config):
        error = StreamEvent(
            message_type=MessageType.RESULT,
            is_complete=True,
            error="stream disconnected before completion: stream closed before response.completed",
        )
        (result,) = await self._run(LocalCodexRunner(local_config=local_config), [error])
        assert "ended the response stream early" in (result.error or "")
        assert "/ollama use" in (result.error or "")
        # The original transport message is kept — the hint is added, not swapped.
        assert "stream disconnected before completion" in (result.error or "")

    async def test_leaves_other_errors_alone(self, local_config):
        error = StreamEvent(
            message_type=MessageType.RESULT, is_complete=True, error="model not found"
        )
        (result,) = await self._run(LocalCodexRunner(local_config=local_config), [error])
        assert result.error == "model not found"

    async def test_passes_ordinary_events_through(self, local_config):
        text = StreamEvent(message_type=MessageType.ASSISTANT, text="hello")
        (result,) = await self._run(LocalCodexRunner(local_config=local_config), [text])
        assert result.text == "hello"


class TestFactory:
    def test_create_backend_builds_the_local_runner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CCDB_LOCAL_CODEX_HOME", str(tmp_path / "home"))
        runner = create_backend(backend="local", model="gpt-oss:120b")
        assert isinstance(runner, LocalCodexRunner)

    def test_unknown_backend_still_raises(self):
        with pytest.raises(ValueError):
            create_backend(backend="telepathy")

    def test_local_is_a_selectable_backend(self):
        from claude_discord.backend_settings import ALL_BACKENDS

        assert "local" in ALL_BACKENDS

    def test_local_uses_the_codex_command(self):
        from claude_discord.backend_factory import BackendFactory

        factory = BackendFactory(
            claude_command="claude",
            codex_command="codex",
            permission_mode="default",
            working_dir=None,
            timeout_seconds=300,
            dangerously_skip_permissions=False,
            allowed_tools=None,
            append_system_prompt=None,
            effort=None,
        )
        assert factory.command_for("local") == "codex"

    def test_local_runner_is_tagged_local_in_embeds(self, local_config):
        from claude_discord.cogs.event_processor import _backend_name_from_runner

        # LocalCodexRunner subclasses CodexRunner — the check must not fall through.
        assert _backend_name_from_runner(LocalCodexRunner(local_config=local_config)) == "local"
