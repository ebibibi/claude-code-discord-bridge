"""Tests for the ``/ollama`` command group.

Discord plumbing is mocked; what is asserted is the judgement the commands make
before touching state. Three of those matter enough to pin down:

* Selecting a model that is not installed, or that cannot call tools, must be
  refused or flagged *here* — the alternative is a Codex session that fails
  inside a thread, minutes later, with an error that names neither cause.
* Deleting the model the backend is set to use must be refused, because the
  breakage would surface on the next turn rather than on the command.
* Autocomplete must degrade to an empty list when the server is unreachable.
  Discord gives it three seconds and no way to show an error.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from claude_code_core.local_backend import LocalModelConfig
from claude_code_core.ollama_client import OllamaError, OllamaModel
from claude_discord.backend_settings import BackendSettings
from claude_discord.cogs import ollama_command as mod
from claude_discord.cogs.ollama_command import OllamaCommandCog
from claude_discord.database.settings_repo import SettingsRepository

CONFIG = LocalModelConfig(base_url="http://host:11434/v1", model="gpt-oss:120b")


def model(name: str, *, size_gb: float = 10.0, tools: bool = True) -> OllamaModel:
    return OllamaModel(
        name=name,
        size_bytes=int(size_gb * 1_000_000_000),
        parameter_size="30B",
        quantization="Q4_K_M",
        family="test",
        capabilities=("completion", "tools") if tools else ("completion",),
    )


async def _settings() -> BackendSettings:
    tmp = Path(tempfile.mkdtemp()) / "settings.db"
    async with aiosqlite.connect(str(tmp)) as db:
        await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await db.commit()
    return BackendSettings(
        SettingsRepository(str(tmp)),
        env_backend="local",
        env_model_for_claude=None,
        env_model_for_codex=None,
    )


async def _cog(settings: BackendSettings | None = None) -> tuple[OllamaCommandCog, MagicMock]:
    settings = settings or await _settings()
    chat_cog = MagicMock()
    chat_cog.runner = MagicMock()
    chat_cog.runner.model = "gpt-oss:120b"
    cog = OllamaCommandCog(MagicMock(), settings=settings, chat_cog=chat_cog, config=CONFIG)
    return cog, chat_cog


def _interaction(thread_id: int | None = None) -> MagicMock:
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    if thread_id is None:
        interaction.channel = MagicMock(spec=[])  # not a Thread
    else:
        import discord

        thread = MagicMock(spec=discord.Thread)
        thread.id = thread_id
        thread.send = AsyncMock()
        interaction.channel = thread
    return interaction


def _sent(interaction: MagicMock) -> str:
    """The text of whatever the command actually posted."""
    for call in (
        interaction.followup.send.call_args,
        interaction.response.send_message.call_args,
    ):
        if call is not None:
            return str(call.args[0]) if call.args else str(call.kwargs.get("content", ""))
    raise AssertionError("nothing was sent")


class TestUse:
    @pytest.mark.asyncio
    async def test_refuses_a_model_that_is_not_installed(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[model("other:7b")]))
        interaction = _interaction()

        await cog.use.callback(cog, interaction, "missing:70b")

        message = _sent(interaction)
        assert "not installed" in message
        # And it must not have been stored — a stored-but-absent model is
        # exactly the state that fails later instead of now.
        assert await cog._settings.current_model("local", None) is None

    @pytest.mark.asyncio
    async def test_selects_an_installed_model_globally(self, monkeypatch):
        cog, chat_cog = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[model("qwen3.6:35b")]))
        interaction = _interaction()

        await cog.use.callback(cog, interaction, "qwen3.6:35b")

        assert await cog._settings.current_model("local", None) == "qwen3.6:35b"
        # Without this the setting is stored but the live runner keeps the old
        # model until the next bot restart.
        assert chat_cog.runner.model == "qwen3.6:35b"

    @pytest.mark.asyncio
    async def test_warns_when_the_model_cannot_call_tools(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(
            mod, "list_models", AsyncMock(return_value=[model("prose:7b", tools=False)])
        )
        interaction = _interaction()

        await cog.use.callback(cog, interaction, "prose:7b")

        assert "tool calling" in _sent(interaction)
        # Warned, not blocked: the operator may know something we do not.
        assert await cog._settings.current_model("local", None) == "prose:7b"

    @pytest.mark.asyncio
    async def test_thread_scope_does_not_touch_the_global_runner(self, monkeypatch):
        cog, chat_cog = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[model("qwen3.6:35b")]))
        interaction = _interaction(thread_id=42)

        await cog.use.callback(cog, interaction, "qwen3.6:35b", thread_only=True)

        assert await cog._settings.current_model("local", 42) == "qwen3.6:35b"
        assert chat_cog.runner.model == "gpt-oss:120b"

    @pytest.mark.asyncio
    async def test_thread_scope_outside_a_thread_is_refused(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[model("m:7b")]))
        interaction = _interaction()

        await cog.use.callback(cog, interaction, "m:7b", thread_only=True)

        assert "inside a thread" in _sent(interaction)

    @pytest.mark.asyncio
    async def test_an_unreachable_server_does_not_block_a_selection(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(side_effect=OllamaError("refused")))
        interaction = _interaction()

        await cog.use.callback(cog, interaction, "qwen3.6:35b")

        assert await cog._settings.current_model("local", None) == "qwen3.6:35b"
        assert "Could not verify" in _sent(interaction)

    @pytest.mark.asyncio
    async def test_rejects_a_malformed_name(self, monkeypatch):
        cog, _ = await _cog()
        listing = AsyncMock(return_value=[])
        monkeypatch.setattr(mod, "list_models", listing)
        interaction = _interaction()

        await cog.use.callback(cog, interaction, "not a model name")

        assert "Invalid Ollama model name" in _sent(interaction)
        listing.assert_not_awaited()


class TestRemove:
    @pytest.mark.asyncio
    async def test_refuses_to_delete_the_selected_model(self, monkeypatch):
        settings = await _settings()
        await settings.set_model("local", "gpt-oss:120b", thread_id=None)
        cog, _ = await _cog(settings)
        deleter = AsyncMock()
        monkeypatch.setattr(mod, "delete_model", deleter)
        interaction = _interaction()

        await cog.rm.callback(cog, interaction, "gpt-oss:120b")

        deleter.assert_not_awaited()
        assert "set to use" in _sent(interaction)

    @pytest.mark.asyncio
    async def test_deletes_an_unused_model(self, monkeypatch):
        settings = await _settings()
        await settings.set_model("local", "keeper:7b", thread_id=None)
        cog, _ = await _cog(settings)
        deleter = AsyncMock()
        monkeypatch.setattr(mod, "delete_model", deleter)
        interaction = _interaction()

        await cog.rm.callback(cog, interaction, "old:7b")

        deleter.assert_awaited_once()
        assert "Deleted" in _sent(interaction)


class TestListing:
    @pytest.mark.asyncio
    async def test_marks_the_selected_model_and_flags_missing_tool_support(self, monkeypatch):
        settings = await _settings()
        await settings.set_model("local", "chosen:30b", thread_id=None)
        cog, _ = await _cog(settings)
        monkeypatch.setattr(
            mod,
            "list_models",
            AsyncMock(return_value=[model("chosen:30b"), model("prose:7b", tools=False)]),
        )
        interaction = _interaction()

        await cog.list_command.callback(cog, interaction)

        message = _sent(interaction)
        assert "▶ chosen:30b" in message
        assert "NO-TOOLS" in message
        assert "prose:7b" in message

    @pytest.mark.asyncio
    async def test_an_empty_server_points_at_the_next_command(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[]))
        interaction = _interaction()

        await cog.list_command.callback(cog, interaction)

        assert "/ollama pull" in _sent(interaction)

    @pytest.mark.asyncio
    async def test_a_long_listing_says_what_it_dropped(self, monkeypatch):
        # Silent truncation reads as "that model is not installed".
        cog, _ = await _cog()
        many = [model(f"model-number-{i:03d}:30b") for i in range(80)]
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=many))
        interaction = _interaction()

        await cog.list_command.callback(cog, interaction)

        message = _sent(interaction)
        assert len(message) <= 2000
        assert "not shown" in message


class TestPs:
    @pytest.mark.asyncio
    async def test_nothing_loaded_is_explained_not_treated_as_an_error(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "running_models", AsyncMock(return_value=[]))
        interaction = _interaction()

        await cog.ps.callback(cog, interaction)

        assert "Nothing is loaded" in _sent(interaction)

    @pytest.mark.asyncio
    async def test_spilling_to_system_ram_is_called_out(self, monkeypatch):
        from claude_code_core.ollama_client import RunningModel

        cog, _ = await _cog()
        monkeypatch.setattr(
            mod,
            "running_models",
            AsyncMock(
                return_value=[
                    RunningModel(
                        name="big:120b",
                        size_bytes=80_000_000_000,
                        size_vram_bytes=40_000_000_000,
                        context_length=32768,
                    )
                ]
            ),
        )
        interaction = _interaction()

        await cog.ps.callback(cog, interaction)

        assert "spilling to system RAM" in _sent(interaction)


class TestAutocomplete:
    @pytest.mark.asyncio
    async def test_installed_autocomplete_is_empty_when_the_server_is_down(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(side_effect=OllamaError("refused")))
        assert await cog._installed_autocomplete(_interaction(), "") == []

    @pytest.mark.asyncio
    async def test_installed_autocomplete_filters_on_what_was_typed(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(
            mod, "list_models", AsyncMock(return_value=[model("qwen3.6:35b"), model("gemma4:31b")])
        )
        choices = await cog._installed_autocomplete(_interaction(), "qwen")
        assert [c.value for c in choices] == ["qwen3.6:35b"]

    @pytest.mark.asyncio
    async def test_catalog_autocomplete_marks_already_installed_entries(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[model("gpt-oss:120b")]))
        choices = await cog._catalog_autocomplete(_interaction(), "gpt-oss")
        labels = {c.value: c.name for c in choices}
        assert "[installed]" in labels["gpt-oss:120b"]
        assert "[installed]" in labels["gpt-oss:20b"]  # same stem, already pulled

    @pytest.mark.asyncio
    async def test_catalog_autocomplete_accepts_a_tag_outside_the_catalog(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[]))
        choices = await cog._catalog_autocomplete(_interaction(), "some-new-model:8b")
        assert [c.value for c in choices] == ["some-new-model:8b"]

    @pytest.mark.asyncio
    async def test_every_choice_fits_discords_label_limit(self, monkeypatch):
        cog, _ = await _cog()
        monkeypatch.setattr(mod, "list_models", AsyncMock(return_value=[]))
        choices = await cog._catalog_autocomplete(_interaction(), "")
        assert choices and all(len(c.name) <= 100 for c in choices)
