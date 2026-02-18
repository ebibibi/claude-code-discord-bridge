"""Tests for AutoUpgradeCog."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from claude_discord.cogs.auto_upgrade import AutoUpgradeCog, UpgradeConfig

_PATCH_EXEC = "asyncio.create_subprocess_exec"
_PATCH_WAIT = "asyncio.wait_for"
_PATCH_SLEEP = "asyncio.sleep"


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock(spec=commands.Bot)


@pytest.fixture
def config() -> UpgradeConfig:
    return UpgradeConfig(
        package_name="claude-code-discord-bridge",
        trigger_prefix="🔄 ebibot-upgrade",
        working_dir="/home/user/bot",
    )


@pytest.fixture
def cog(bot: MagicMock, config: UpgradeConfig) -> AutoUpgradeCog:
    return AutoUpgradeCog(bot=bot, config=config)


def _make_message(
    content: str = "🔄 ebibot-upgrade",
    webhook_id: int | None = 12345,
    channel_id: int = 999,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.webhook_id = webhook_id
    msg.channel = MagicMock()
    msg.channel.id = channel_id
    msg.reply = AsyncMock()
    msg.add_reaction = AsyncMock()
    thread = MagicMock(spec=discord.Thread)
    thread.send = AsyncMock()
    msg.create_thread = AsyncMock(return_value=thread)
    return msg


def _make_process(
    returncode: int = 0, stdout: bytes = b"ok",
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


class TestFiltering:
    """Test message filtering logic."""

    @pytest.mark.asyncio
    async def test_ignores_non_webhook(
        self, cog: AutoUpgradeCog,
    ) -> None:
        msg = _make_message(webhook_id=None)
        msg.create_thread = AsyncMock()
        await cog.on_message(msg)
        msg.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unauthorized_webhook(
        self, bot: MagicMock,
    ) -> None:
        config = UpgradeConfig(
            package_name="pkg",
            allowed_webhook_ids={99999},
        )
        cog = AutoUpgradeCog(bot=bot, config=config)
        msg = _make_message(webhook_id=12345)
        msg.create_thread = AsyncMock()
        await cog.on_message(msg)
        msg.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_wrong_channel(
        self, bot: MagicMock,
    ) -> None:
        config = UpgradeConfig(
            package_name="pkg",
            channel_ids={111},
        )
        cog = AutoUpgradeCog(bot=bot, config=config)
        msg = _make_message(channel_id=999)
        msg.create_thread = AsyncMock()
        await cog.on_message(msg)
        msg.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_wrong_prefix(
        self, cog: AutoUpgradeCog,
    ) -> None:
        msg = _make_message(content="Hello")
        msg.create_thread = AsyncMock()
        await cog.on_message(msg)
        msg.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_exact_match_required(
        self, cog: AutoUpgradeCog,
    ) -> None:
        """Trigger prefix must be exact match."""
        msg = _make_message(content="🔄 ebibot-upgrade extra")
        msg.create_thread = AsyncMock()
        await cog.on_message(msg)
        msg.create_thread.assert_not_called()


class TestUpgradeSteps:
    """Test upgrade step execution.

    All subprocess calls use create_subprocess_exec with args
    from UpgradeConfig, not user input.
    """

    @pytest.mark.asyncio
    async def test_upgrade_failure_adds_error_reaction(
        self, cog: AutoUpgradeCog,
    ) -> None:
        """If upgrade step fails, should add error reaction."""
        msg = _make_message()
        proc_fail = _make_process(returncode=1, stdout=b"error")
        with (
            patch(_PATCH_EXEC, new_callable=AsyncMock, return_value=proc_fail),
            patch(_PATCH_WAIT, new_callable=AsyncMock, return_value=(b"error", b"")),
        ):
            await cog.on_message(msg)

        msg.add_reaction.assert_called_with("❌")

    @pytest.mark.asyncio
    async def test_success_adds_check_reaction(
        self, cog: AutoUpgradeCog,
    ) -> None:
        """Successful upgrade should add check reaction."""
        msg = _make_message()
        proc_ok = _make_process()
        with (
            patch(_PATCH_EXEC, new_callable=AsyncMock, return_value=proc_ok),
            patch(_PATCH_WAIT, new_callable=AsyncMock, return_value=(b"ok", b"")),
        ):
            await cog.on_message(msg)

        msg.add_reaction.assert_called_with("✅")

    @pytest.mark.asyncio
    async def test_no_restart_shows_completion(
        self, cog: AutoUpgradeCog,
    ) -> None:
        """When no restart_command, show completion message."""
        msg = _make_message()
        thread = msg.create_thread.return_value
        proc_ok = _make_process()
        with (
            patch(_PATCH_EXEC, new_callable=AsyncMock, return_value=proc_ok),
            patch(_PATCH_WAIT, new_callable=AsyncMock, return_value=(b"ok", b"")),
        ):
            await cog.on_message(msg)

        send_calls = [str(c) for c in thread.send.call_args_list]
        assert any("Upgrade complete" in s for s in send_calls)

    @pytest.mark.asyncio
    async def test_restart_command_fired(
        self, bot: MagicMock,
    ) -> None:
        """Restart command should be fired after upgrade.

        The restart command uses create_subprocess_exec with
        args from UpgradeConfig, not from user/webhook input.
        """
        config = UpgradeConfig(
            package_name="pkg",
            restart_command=[
                "sudo", "systemctl", "restart", "bot.service",
            ],
            working_dir="/tmp",
        )
        cog = AutoUpgradeCog(bot=bot, config=config)
        msg = _make_message(content="🔄 upgrade")

        proc_ok = _make_process()
        exec_calls: list[tuple] = []

        async def mock_subprocess_exec(*args, **kwargs):
            exec_calls.append(args)
            return proc_ok

        with (
            patch(_PATCH_EXEC, side_effect=mock_subprocess_exec),
            patch(_PATCH_WAIT, new_callable=AsyncMock, return_value=(b"ok", b"")),
            patch(_PATCH_SLEEP, new_callable=AsyncMock),
        ):
            await cog.on_message(msg)

        assert len(exec_calls) == 3
        assert exec_calls[2] == (
            "sudo", "systemctl", "restart", "bot.service",
        )


class TestDrainCheck:
    """Test graceful-drain-before-restart behaviour."""

    def _make_cog_with_restart(
        self,
        bot: MagicMock,
        drain_check=None,
        drain_timeout: int = 300,
        drain_poll_interval: int = 10,
    ) -> AutoUpgradeCog:
        config = UpgradeConfig(
            package_name="pkg",
            restart_command=["sudo", "systemctl", "restart", "bot.service"],
            working_dir="/tmp",
        )
        return AutoUpgradeCog(
            bot=bot,
            config=config,
            drain_check=drain_check,
            drain_timeout=drain_timeout,
            drain_poll_interval=drain_poll_interval,
        )

    @pytest.mark.asyncio
    async def test_no_drain_check_skips_waiting(
        self, bot: MagicMock,
    ) -> None:
        """When drain_check is None, _drain returns immediately."""
        cog = self._make_cog_with_restart(bot)
        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        with patch(_PATCH_SLEEP, new_callable=AsyncMock) as mock_sleep:
            await cog._drain(thread)

        mock_sleep.assert_not_called()
        thread.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_check_true_returns_immediately(
        self, bot: MagicMock,
    ) -> None:
        """When drain_check already returns True, no polling occurs."""
        cog = self._make_cog_with_restart(bot, drain_check=lambda: True)
        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        with patch(_PATCH_SLEEP, new_callable=AsyncMock) as mock_sleep:
            await cog._drain(thread)

        mock_sleep.assert_not_called()
        thread.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_waits_until_check_passes(
        self, bot: MagicMock,
    ) -> None:
        """drain_check False→True: polls once then proceeds."""
        poll_count = 0

        def drain_check() -> bool:
            nonlocal poll_count
            poll_count += 1
            return poll_count > 1  # False first, True second

        cog = self._make_cog_with_restart(
            bot, drain_check=drain_check, drain_poll_interval=5,
        )
        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        sleep_calls: list[float] = []

        async def capture_sleep(s: float) -> None:
            sleep_calls.append(s)

        with patch(_PATCH_SLEEP, side_effect=capture_sleep):
            await cog._drain(thread)

        assert sleep_calls == [5]
        send_texts = " ".join(str(c) for c in thread.send.call_args_list)
        assert "waiting for active sessions" in send_texts
        assert "Sessions finished" in send_texts

    @pytest.mark.asyncio
    async def test_drain_timeout_proceeds_anyway(
        self, bot: MagicMock,
    ) -> None:
        """When drain_check never returns True, returns after timeout."""
        cog = self._make_cog_with_restart(
            bot,
            drain_check=lambda: False,
            drain_timeout=20,
            drain_poll_interval=10,
        )
        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        with patch(_PATCH_SLEEP, new_callable=AsyncMock):
            await cog._drain(thread)

        # Posts timeout warning, then returns (restart proceeds)
        send_texts = " ".join(str(c) for c in thread.send.call_args_list)
        assert "timeout" in send_texts.lower()


class TestConcurrency:
    """Test concurrent execution prevention."""

    @pytest.mark.asyncio
    async def test_concurrent_blocked(
        self, cog: AutoUpgradeCog,
    ) -> None:
        msg = _make_message()
        await cog._lock.acquire()
        try:
            await cog.on_message(msg)
            msg.reply.assert_called_once()
            assert "already running" in msg.reply.call_args[0][0]
        finally:
            cog._lock.release()


class TestUpgradeConfigDataclass:
    """Test UpgradeConfig dataclass."""

    def test_defaults(self) -> None:
        config = UpgradeConfig(package_name="my-pkg")
        assert config.package_name == "my-pkg"
        assert config.trigger_prefix == "🔄 upgrade"
        assert config.working_dir == "."
        assert config.upgrade_command is None
        assert config.sync_command is None
        assert config.restart_command is None
        assert config.allowed_webhook_ids is None
        assert config.channel_ids is None
        assert config.step_timeout == 120

    def test_frozen(self) -> None:
        config = UpgradeConfig(package_name="my-pkg")
        with pytest.raises(AttributeError):
            config.package_name = "changed"  # type: ignore[misc]

    def test_custom_commands(self) -> None:
        config = UpgradeConfig(
            package_name="my-pkg",
            upgrade_command=["pip", "install", "--upgrade", "my-pkg"],
            sync_command=["pip", "check"],
        )
        assert config.upgrade_command == [
            "pip", "install", "--upgrade", "my-pkg",
        ]
        assert config.sync_command == ["pip", "check"]


class TestActiveSessionCount:
    """Tests for ClaudeChatCog.active_session_count property."""

    def test_count_starts_at_zero(self) -> None:
        from claude_discord.cogs.claude_chat import ClaudeChatCog
        from claude_discord.claude.runner import ClaudeRunner

        bot = MagicMock()
        bot.channel_id = 999
        cog = ClaudeChatCog(
            bot=bot,
            repo=MagicMock(),
            runner=MagicMock(spec=ClaudeRunner),
        )
        assert cog.active_session_count == 0

    def test_count_reflects_runners(self) -> None:
        from claude_discord.cogs.claude_chat import ClaudeChatCog
        from claude_discord.claude.runner import ClaudeRunner

        bot = MagicMock()
        bot.channel_id = 999
        cog = ClaudeChatCog(
            bot=bot,
            repo=MagicMock(),
            runner=MagicMock(spec=ClaudeRunner),
        )
        cog._active_runners[1] = MagicMock()
        cog._active_runners[2] = MagicMock()
        assert cog.active_session_count == 2

        del cog._active_runners[1]
        assert cog.active_session_count == 1
