"""Tests for /model command group in SessionManageCog.

TDD: Write tests first, then implement.

Commands:
- /model show  — display current global model (+ per-thread model if in thread)
- /model set   — update global default model in settings_repo
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs.session_manage import (
    SETTING_CLAUDE_MODEL,
    SessionManageCog,
)
from claude_discord.database.repository import SessionRecord


def _make_record(
    thread_id: int = 100,
    session_id: str = "abc-123",
    model: str | None = "sonnet",
) -> SessionRecord:
    return SessionRecord(
        thread_id=thread_id,
        session_id=session_id,
        working_dir="/home/user",
        model=model,
        origin="discord",
        summary=None,
        created_at="2026-02-22 10:00:00",
        last_used_at="2026-02-22 11:00:00",
    )


def _make_thread_interaction(thread_id: int = 12345) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    interaction.channel = thread
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_channel_interaction() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_cog(
    default_model: str = "sonnet",
    settings_model: str | None = None,
) -> SessionManageCog:
    from claude_discord.cogs.session_manage import SessionManageCog

    bot = MagicMock()
    bot.channel_id = 999

    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])

    settings_repo = MagicMock()
    settings_repo.get = AsyncMock(return_value=settings_model)
    settings_repo.set = AsyncMock()

    runner = MagicMock()
    runner.model = default_model

    return SessionManageCog(
        bot=bot,
        repo=repo,
        settings_repo=settings_repo,
        runner=runner,
    )


class TestModelShow:
    async def test_show_global_model_in_channel(self):
        """In a channel (not thread), show the global model."""
        cog = _make_cog(default_model="sonnet", settings_model=None)
        interaction = _make_channel_interaction()
        await cog.model_show.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        # Global model should appear in the embed
        assert "sonnet" in embed.description.lower() or any(
            "sonnet" in str(f.value).lower() for f in embed.fields
        )

    async def test_show_settings_model_overrides_runner(self):
        """settings_repo model takes precedence over runner.model."""
        cog = _make_cog(default_model="sonnet", settings_model="opus")
        interaction = _make_channel_interaction()
        await cog.model_show.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        text = embed.description + " ".join(str(f.value) for f in embed.fields)
        assert "opus" in text.lower()

    async def test_show_thread_model_from_session(self):
        """In a thread with a session, also show the per-thread model."""
        cog = _make_cog(default_model="sonnet", settings_model=None)
        record = _make_record(thread_id=12345, model="haiku")
        cog.repo.get = AsyncMock(return_value=record)

        interaction = _make_thread_interaction(thread_id=12345)
        await cog.model_show.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        text = embed.description + " ".join(str(f.value) for f in embed.fields)
        assert "haiku" in text.lower()

    async def test_show_no_session_in_thread(self):
        """In a thread with no session, only show global model."""
        cog = _make_cog(default_model="sonnet", settings_model=None)
        cog.repo.get = AsyncMock(return_value=None)

        interaction = _make_thread_interaction(thread_id=12345)
        await cog.model_show.callback(cog, interaction)
        # Should succeed without error
        assert interaction.response.send_message.called

    async def test_show_no_settings_repo(self):
        """Graceful fallback when settings_repo is None."""
        from claude_discord.cogs.session_manage import SessionManageCog

        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        runner = MagicMock()
        runner.model = "sonnet"

        cog = SessionManageCog(bot=bot, repo=repo, runner=runner)
        interaction = _make_channel_interaction()
        await cog.model_show.callback(cog, interaction)
        assert interaction.response.send_message.called


class TestModelSet:
    async def test_set_valid_model(self):
        """Setting a valid model stores it in settings_repo."""
        cog = _make_cog()
        interaction = _make_channel_interaction()
        await cog.model_set.callback(cog, interaction, model="opus")
        cog.settings_repo.set.assert_awaited_once_with(SETTING_CLAUDE_MODEL, "opus")

    async def test_set_model_sends_confirmation(self):
        """Setting a model sends a confirmation embed."""
        cog = _make_cog()
        interaction = _make_channel_interaction()
        await cog.model_set.callback(cog, interaction, model="haiku")
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "haiku" in embed.description.lower() or any(
            "haiku" in str(f.value).lower() for f in embed.fields
        )

    async def test_set_invalid_model_rejected(self):
        """Setting an unsupported model shows an error, does not save."""
        cog = _make_cog()
        interaction = _make_channel_interaction()
        await cog.model_set.callback(cog, interaction, model="gpt-4")
        # settings_repo.set should NOT be called for invalid models
        cog.settings_repo.set.assert_not_awaited()
        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

    async def test_set_model_no_settings_repo(self):
        """When settings_repo is None, set sends ephemeral error."""
        from claude_discord.cogs.session_manage import SessionManageCog

        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        runner = MagicMock()
        runner.model = "sonnet"

        cog = SessionManageCog(bot=bot, repo=repo, runner=runner)
        interaction = _make_channel_interaction()
        await cog.model_set.callback(cog, interaction, model="opus")
        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

    @pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"])
    async def test_all_valid_models_accepted(self, model: str):
        """All documented model names should be accepted."""
        cog = _make_cog()
        interaction = _make_channel_interaction()
        await cog.model_set.callback(cog, interaction, model=model)
        cog.settings_repo.set.assert_awaited_once_with(SETTING_CLAUDE_MODEL, model)
