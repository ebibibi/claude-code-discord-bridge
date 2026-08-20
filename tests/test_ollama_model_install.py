"""Tests for installing and selecting Ollama models through /model."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
from discord import app_commands

from claude_code_core.local_backend import (
    LocalModelConfig,
    ollama_pull_url,
    pull_ollama_model,
    validate_ollama_model_name,
)
from claude_discord.backend_factory import BackendFactory
from claude_discord.backend_settings import BackendSettings
from claude_discord.cogs.backend_command import BackendCommandCog
from claude_discord.database.settings_repo import SettingsRepository

MODEL = "qwen3.6:35b-a3b-mtp-q4_K_M"


class _FakeResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.fixture
def local_config(tmp_path: Path) -> LocalModelConfig:
    return LocalModelConfig(
        base_url="http://192.168.1.3:11434/v1",
        model="gpt-oss:120b",
        codex_home=tmp_path / "local-codex-home",
    )


class TestOllamaPull:
    def test_derives_native_pull_endpoint_from_openai_compatible_url(self) -> None:
        assert ollama_pull_url("http://192.168.1.3:11434/v1") == (
            "http://192.168.1.3:11434/api/pull"
        )

    def test_accepts_realistic_ollama_model_name(self) -> None:
        assert validate_ollama_model_name(MODEL) == MODEL

    @pytest.mark.parametrize("model", ["", "has space:7b", "model?tag", "model#tag"])
    def test_rejects_invalid_model_names(self, model: str) -> None:
        with pytest.raises(ValueError, match="Ollama model name"):
            validate_ollama_model_name(model)

    async def test_pull_posts_non_streaming_request(
        self,
        local_config: LocalModelConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def _urlopen(request, *, timeout: float):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeResponse({"status": "success"})

        monkeypatch.setattr("claude_code_core.ollama_client.urllib_request.urlopen", _urlopen)

        await pull_ollama_model(MODEL, config=local_config)

        assert captured["url"] == "http://192.168.1.3:11434/api/pull"
        assert captured["method"] == "POST"
        assert captured["body"] == {"model": MODEL, "stream": False}

    async def test_pull_rejects_non_success_response(
        self,
        local_config: LocalModelConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _urlopen(request, *, timeout: float):
            return _FakeResponse({"status": "pulling manifest"})

        monkeypatch.setattr("claude_code_core.ollama_client.urllib_request.urlopen", _urlopen)

        with pytest.raises(RuntimeError, match="did not complete successfully"):
            await pull_ollama_model(MODEL, config=local_config)


async def _new_settings_repo() -> SettingsRepository:
    tmp = Path(tempfile.mkdtemp()) / "settings.db"
    async with aiosqlite.connect(str(tmp)) as db:
        await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await db.commit()
    return SettingsRepository(str(tmp))


async def _settings() -> BackendSettings:
    repo = await _new_settings_repo()
    return BackendSettings(
        repo,
        env_backend="claude",
        env_model_for_claude="sonnet",
        env_model_for_codex="",
    )


def _make_cog(settings: BackendSettings) -> tuple[BackendCommandCog, MagicMock]:
    factory = BackendFactory(
        claude_command="claude",
        codex_command="codex",
        permission_mode="acceptEdits",
        working_dir=None,
        timeout_seconds=300,
        dangerously_skip_permissions=False,
        allowed_tools=None,
        append_system_prompt=None,
        effort=None,
    )
    chat_cog = MagicMock()
    chat_cog.runner = MagicMock()
    cog = BackendCommandCog(MagicMock(), settings=settings, factory=factory, chat_cog=chat_cog)
    return cog, chat_cog


def _model_subcommand(cog: BackendCommandCog, name: str) -> app_commands.Command:
    group = next(command for command in cog.get_app_commands() if command.name == "model")
    assert isinstance(group, app_commands.Group)
    command = group.get_command(name)
    assert isinstance(command, app_commands.Command)
    return command


def _channel_interaction() -> MagicMock:
    interaction = MagicMock()
    interaction.channel = MagicMock()
    interaction.channel.send = AsyncMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestModelDiscordCommandShape:
    async def test_model_is_a_group_with_visible_subcommands(self) -> None:
        settings = await _settings()
        cog, _ = _make_cog(settings)

        roots = {command.name: command for command in cog.get_app_commands()}
        model = roots["model"]

        assert isinstance(model, app_commands.Group)
        assert [command.name for command in model.commands] == ["show", "set", "install"]
        assert [command.qualified_name for command in model.commands] == [
            "model show",
            "model set",
            "model install",
        ]

    async def test_set_subcommand_selects_model(self) -> None:
        settings = await _settings()
        cog, chat_cog = _make_cog(settings)
        interaction = _channel_interaction()

        command = _model_subcommand(cog, "set")
        await command.callback(cog, interaction, name="opus", scope="global")

        assert await settings.current_model("claude") == "opus"
        assert chat_cog.runner.model == "opus"
        message = interaction.response.send_message.await_args.args[0]
        assert "Model set" in message


class TestModelInstallCommand:
    async def test_local_install_pulls_then_selects_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = await _settings()
        await settings.set_backend("local")
        cog, chat_cog = _make_cog(settings)
        interaction = _channel_interaction()
        pull = AsyncMock()
        monkeypatch.setattr("claude_discord.cogs.backend_command.pull_ollama_model", pull)

        command = _model_subcommand(cog, "install")
        await command.callback(cog, interaction, name=MODEL, scope="global")

        pull.assert_awaited_once_with(MODEL)
        assert await settings.current_model("local") == MODEL
        assert chat_cog.runner.model == MODEL
        started = interaction.response.send_message.await_args.args[0]
        assert "Installing" in started
        completed = interaction.channel.send.await_args.args[0]
        assert "Installed" in completed
        assert MODEL in completed

    async def test_install_is_rejected_for_non_local_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = await _settings()
        cog, _ = _make_cog(settings)
        interaction = _channel_interaction()
        pull = AsyncMock()
        monkeypatch.setattr("claude_discord.cogs.backend_command.pull_ollama_model", pull)

        command = _model_subcommand(cog, "install")
        await command.callback(cog, interaction, name=MODEL, scope="global")

        pull.assert_not_awaited()
        assert await settings.explicit_model("claude") is None
        message = interaction.response.send_message.await_args.args[0]
        assert "local" in message.lower()

    async def test_failed_pull_does_not_select_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = await _settings()
        await settings.set_backend("local")
        cog, _ = _make_cog(settings)
        interaction = _channel_interaction()
        pull = AsyncMock(side_effect=RuntimeError("offline"))
        monkeypatch.setattr("claude_discord.cogs.backend_command.pull_ollama_model", pull)

        command = _model_subcommand(cog, "install")
        await command.callback(cog, interaction, name=MODEL, scope="global")

        assert await settings.explicit_model("local") is None
        completed = interaction.channel.send.await_args.args[0]
        assert "failed" in completed.lower()
