"""Tests for /tools command group in SessionManageCog.

Commands:
- /tools-show  — display current allowed tools
- /tools-set   — show select menu to pick tools
- /tools-reset — revert to .env default
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from claude_discord.cogs.session_manage import (
    KNOWN_TOOLS,
    SETTING_ALLOWED_TOOLS,
    SessionManageCog,
)
from claude_discord.discord_ui.views import ToolSelectView


def _make_interaction() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    return interaction


def _make_cog(
    runner_tools: list[str] | None = None,
    settings_tools: str | None = None,
) -> SessionManageCog:
    bot = MagicMock()
    bot.channel_id = 999

    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])

    settings_repo = MagicMock()

    async def _settings_get(key: str, *, default: str | None = None) -> str | None:
        if key == SETTING_ALLOWED_TOOLS:
            return settings_tools
        return default

    settings_repo.get = AsyncMock(side_effect=_settings_get)
    settings_repo.set = AsyncMock()
    settings_repo.delete = AsyncMock(return_value=settings_tools is not None)

    runner = MagicMock()
    runner.model = "sonnet"
    runner.allowed_tools = runner_tools

    return SessionManageCog(
        bot=bot,
        repo=repo,
        settings_repo=settings_repo,
        runner=runner,
    )


class TestToolsShow:
    async def test_show_no_restrictions(self) -> None:
        """When no tools configured, show 'no restrictions'."""
        cog = _make_cog(runner_tools=None, settings_tools=None)
        interaction = _make_interaction()
        await cog.tools_show.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "no restrictions" in embed.description.lower()

    async def test_show_runner_defaults(self) -> None:
        """When runner has tools but no settings override, show runner tools."""
        cog = _make_cog(runner_tools=["Bash", "Read"], settings_tools=None)
        interaction = _make_interaction()
        await cog.tools_show.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Bash" in embed.description
        assert "Read" in embed.description

    async def test_show_settings_override(self) -> None:
        """Settings override takes precedence over runner defaults."""
        cog = _make_cog(runner_tools=["Bash"], settings_tools="Bash,Read,Write")
        interaction = _make_interaction()
        await cog.tools_show.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Bash" in embed.description
        assert "Read" in embed.description
        assert "Write" in embed.description

    async def test_show_footer_indicates_source_override(self) -> None:
        """Footer shows 'override' when settings has a value."""
        cog = _make_cog(settings_tools="Bash,Read")
        interaction = _make_interaction()
        await cog.tools_show.callback(cog, interaction)
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "override" in embed.footer.text.lower()

    async def test_show_footer_indicates_env_default(self) -> None:
        """Footer shows '.env default' when using runner tools."""
        cog = _make_cog(runner_tools=["Bash"], settings_tools=None)
        interaction = _make_interaction()
        await cog.tools_show.callback(cog, interaction)
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert ".env" in embed.footer.text


class TestToolsSet:
    async def test_set_sends_view(self) -> None:
        """tools_set sends an ephemeral message with a ToolSelectView."""
        cog = _make_cog()
        interaction = _make_interaction()
        await cog.tools_set.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True
        view = call_args.kwargs.get("view")
        assert isinstance(view, ToolSelectView)

    async def test_set_no_settings_repo(self) -> None:
        """When settings_repo is None, show ephemeral error."""
        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        cog = SessionManageCog(bot=bot, repo=repo)
        interaction = _make_interaction()
        await cog.tools_set.callback(cog, interaction)
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


class TestToolsReset:
    async def test_reset_deletes_setting(self) -> None:
        """tools_reset deletes the override from settings_repo."""
        cog = _make_cog(settings_tools="Bash,Read")
        interaction = _make_interaction()
        await cog.tools_reset.callback(cog, interaction)
        cog.settings_repo.delete.assert_awaited_once_with(SETTING_ALLOWED_TOOLS)

    async def test_reset_shows_revert_message(self) -> None:
        """After reset, embed shows revert confirmation."""
        cog = _make_cog(runner_tools=["Bash"], settings_tools="Bash,Read")
        interaction = _make_interaction()
        await cog.tools_reset.callback(cog, interaction)
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "revert" in embed.description.lower() or "default" in embed.description.lower()

    async def test_reset_no_override_set(self) -> None:
        """When no override was set, show 'already using defaults'."""
        cog = _make_cog(settings_tools=None)
        interaction = _make_interaction()
        await cog.tools_reset.callback(cog, interaction)
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "already" in embed.description.lower() or "default" in embed.description.lower()

    async def test_reset_no_settings_repo(self) -> None:
        """When settings_repo is None, show ephemeral error."""
        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        cog = SessionManageCog(bot=bot, repo=repo)
        interaction = _make_interaction()
        await cog.tools_reset.callback(cog, interaction)
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


class TestToolSelectView:
    async def test_select_options_match_known_tools(self) -> None:
        """View creates options for all known tools."""
        settings_repo = MagicMock()
        view = ToolSelectView(
            known_tools=KNOWN_TOOLS,
            current_tools=["Bash", "Read"],
            settings_repo=settings_repo,
            setting_key=SETTING_ALLOWED_TOOLS,
        )
        select = view._select
        assert len(select.options) == len(KNOWN_TOOLS)
        labels = {opt.label for opt in select.options}
        assert labels == set(KNOWN_TOOLS)

    async def test_current_tools_are_default_selected(self) -> None:
        """Currently enabled tools have default=True in select options."""
        settings_repo = MagicMock()
        view = ToolSelectView(
            known_tools=["Bash", "Read", "Write"],
            current_tools=["Bash", "Write"],
            settings_repo=settings_repo,
            setting_key=SETTING_ALLOWED_TOOLS,
        )
        defaults = {opt.label for opt in view._select.options if opt.default}
        assert defaults == {"Bash", "Write"}

    async def test_no_current_tools_no_defaults(self) -> None:
        """When current_tools is None, no options are pre-selected."""
        settings_repo = MagicMock()
        view = ToolSelectView(
            known_tools=["Bash", "Read"],
            current_tools=None,
            settings_repo=settings_repo,
            setting_key=SETTING_ALLOWED_TOOLS,
        )
        defaults = [opt for opt in view._select.options if opt.default]
        assert defaults == []

    async def test_on_select_saves_to_settings(self) -> None:
        """Selecting tools and submitting saves to settings_repo."""
        settings_repo = MagicMock()
        settings_repo.set = AsyncMock()
        view = ToolSelectView(
            known_tools=["Bash", "Read", "Write"],
            current_tools=None,
            settings_repo=settings_repo,
            setting_key=SETTING_ALLOWED_TOOLS,
        )
        view._select._values = ["Bash", "Read"]
        interaction = _make_interaction()
        await view._on_select(interaction)
        settings_repo.set.assert_awaited_once_with(SETTING_ALLOWED_TOOLS, "Bash,Read")

    async def test_on_select_empty_deletes_setting(self) -> None:
        """Selecting no tools removes the setting (no restrictions)."""
        settings_repo = MagicMock()
        settings_repo.delete = AsyncMock()
        view = ToolSelectView(
            known_tools=["Bash", "Read"],
            current_tools=["Bash"],
            settings_repo=settings_repo,
            setting_key=SETTING_ALLOWED_TOOLS,
        )
        view._select._values = []
        interaction = _make_interaction()
        await view._on_select(interaction)
        settings_repo.delete.assert_awaited_once_with(SETTING_ALLOWED_TOOLS)


class TestKnownToolsList:
    def test_known_tools_not_empty(self) -> None:
        """KNOWN_TOOLS must have at least one tool."""
        assert len(KNOWN_TOOLS) > 0

    def test_known_tools_are_strings(self) -> None:
        """All entries in KNOWN_TOOLS are non-empty strings."""
        for tool in KNOWN_TOOLS:
            assert isinstance(tool, str)
            assert len(tool) > 0
