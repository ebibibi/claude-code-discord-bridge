"""Tests for /upgrade slash command on AutoUpgradeCog.

TDD: write tests first, then implement.

The slash command should:
- Create a thread in the current channel and run the same upgrade pipeline
- Respect upgrade_approval / restart_approval config flags
- Be a no-op when slash_command_enabled=False in UpgradeConfig
- Reply ephemerally when upgrade is already running
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from claude_discord.cogs.auto_upgrade import AutoUpgradeCog, UpgradeConfig

_PATCH_EXEC = "asyncio.create_subprocess_exec"
_PATCH_WAIT = "asyncio.wait_for"


def _make_bot() -> MagicMock:
    bot = MagicMock(spec=commands.Bot)
    bot.cogs = {}
    bot.user = MagicMock()
    bot.user.id = 1
    return bot


def _make_config(slash_command_enabled: bool = True, **kwargs) -> UpgradeConfig:
    defaults = {
        "package_name": "claude-code-discord-bridge",
        "trigger_prefix": "🔄 upgrade",
        "working_dir": "/tmp",
    }
    defaults.update(kwargs)
    return UpgradeConfig(slash_command_enabled=slash_command_enabled, **defaults)


def _make_interaction(channel_id: int = 777) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    # Channel that supports thread creation
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    thread = MagicMock(spec=discord.Thread)
    thread.send = AsyncMock()
    channel.create_thread = AsyncMock(return_value=thread)
    interaction.channel = channel
    return interaction


def _make_process(returncode: int = 0, stdout: bytes = b"ok") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


class TestUpgradeSlashCommandDisabled:
    async def test_disabled_by_default(self):
        """slash_command_enabled defaults to False — safe by default."""
        config = UpgradeConfig(package_name="foo")
        assert config.slash_command_enabled is False

    async def test_command_responds_ephemerally_when_disabled(self):
        """When slash_command_enabled=False, command sends ephemeral error."""
        bot = _make_bot()
        config = _make_config(slash_command_enabled=False)
        cog = AutoUpgradeCog(bot=bot, config=config)
        interaction = _make_interaction()

        await cog.upgrade_command.callback(cog, interaction)

        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True


class TestUpgradeSlashCommandEnabled:
    async def test_creates_thread_and_runs_upgrade(self):
        """When enabled, /upgrade creates a thread and runs the pipeline."""
        bot = _make_bot()
        config = _make_config(slash_command_enabled=True)
        cog = AutoUpgradeCog(bot=bot, config=config)
        interaction = _make_interaction()

        proc = _make_process(returncode=0)
        with (
            patch(_PATCH_EXEC, return_value=proc),
            patch(_PATCH_WAIT, new=AsyncMock(return_value=(b"ok", b""))),
        ):
            await cog.upgrade_command.callback(cog, interaction)

        # Thread should have been created in the channel
        interaction.channel.create_thread.assert_awaited_once()

    async def test_already_running_sends_ephemeral(self):
        """When upgrade is already running, sends ephemeral 'already in progress' message."""
        bot = _make_bot()
        config = _make_config(slash_command_enabled=True)
        cog = AutoUpgradeCog(bot=bot, config=config)
        interaction = _make_interaction()

        # Simulate lock already held
        await cog._lock.acquire()
        try:
            await cog.upgrade_command.callback(cog, interaction)
        finally:
            cog._lock.release()

        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

    async def test_defers_response_before_long_operation(self):
        """Slash command should defer() so Discord doesn't time out."""
        bot = _make_bot()
        config = _make_config(slash_command_enabled=True)
        cog = AutoUpgradeCog(bot=bot, config=config)
        interaction = _make_interaction()

        proc = _make_process(returncode=0)
        with (
            patch(_PATCH_EXEC, return_value=proc),
            patch(_PATCH_WAIT, new=AsyncMock(return_value=(b"ok", b""))),
        ):
            await cog.upgrade_command.callback(cog, interaction)

        interaction.response.defer.assert_awaited_once()

    async def test_thread_name_uses_trigger_prefix(self):
        """The created thread should use trigger_prefix as the name."""
        bot = _make_bot()
        config = _make_config(slash_command_enabled=True, trigger_prefix="🔄 my-bot-upgrade")
        cog = AutoUpgradeCog(bot=bot, config=config)
        interaction = _make_interaction()

        proc = _make_process(returncode=0)
        with (
            patch(_PATCH_EXEC, return_value=proc),
            patch(_PATCH_WAIT, new=AsyncMock(return_value=(b"ok", b""))),
        ):
            await cog.upgrade_command.callback(cog, interaction)

        call_args = interaction.channel.create_thread.call_args
        assert "🔄 my-bot-upgrade" in call_args.kwargs.get("name", "")


class TestUpgradeSlashCommandConfig:
    async def test_slash_command_enabled_field_exists(self):
        """UpgradeConfig should have slash_command_enabled field."""
        config = UpgradeConfig(
            package_name="test",
            slash_command_enabled=True,
        )
        assert config.slash_command_enabled is True

    async def test_slash_command_enabled_false_by_default(self):
        """slash_command_enabled defaults to False for backward compatibility."""
        config = UpgradeConfig(package_name="test")
        assert config.slash_command_enabled is False
