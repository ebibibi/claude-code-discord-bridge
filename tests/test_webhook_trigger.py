"""Tests for WebhookTriggerCog."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from claude_discord.cogs.webhook_trigger import WebhookTrigger, WebhookTriggerCog

_PATCH_RUN = "claude_discord.cogs.webhook_trigger.run_claude_with_config"


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock(spec=commands.Bot)


@pytest.fixture
def runner() -> MagicMock:
    r = MagicMock()
    r.command = "claude"
    r.model = "sonnet"
    r.permission_mode = "acceptEdits"
    r.working_dir = "/home/user"
    r.timeout_seconds = 300
    r.allowed_tools = None
    r.dangerously_skip_permissions = False
    r.include_partial_messages = True
    cloned = MagicMock()
    r.clone.return_value = cloned
    return r


@pytest.fixture
def triggers() -> dict[str, WebhookTrigger]:
    return {
        "🔄 docs-sync": WebhookTrigger(
            prompt="Sync docs",
            working_dir="/home/user/project",
            timeout=600,
        ),
        "🔄 deploy": WebhookTrigger(
            prompt="Deploy to staging",
        ),
    }


@pytest.fixture
def cog(
    bot: MagicMock,
    runner: MagicMock,
    triggers: dict[str, WebhookTrigger],
) -> WebhookTriggerCog:
    return WebhookTriggerCog(
        bot=bot,
        runner=runner,
        triggers=triggers,
    )


def _make_message(
    content: str = "🔄 docs-sync",
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


class TestWebhookFiltering:
    """Test message filtering logic."""

    @pytest.mark.asyncio
    async def test_ignores_non_webhook_messages(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Messages without webhook_id should be ignored."""
        msg = _make_message(webhook_id=None)
        with patch(_PATCH_RUN) as mock_run:
            await cog.on_message(msg)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unauthorized_webhook(
        self,
        bot: MagicMock,
        runner: MagicMock,
        triggers: dict[str, WebhookTrigger],
    ) -> None:
        """Unauthorized webhooks are ignored."""
        cog = WebhookTriggerCog(
            bot=bot,
            runner=runner,
            triggers=triggers,
            allowed_webhook_ids={99999},
        )
        msg = _make_message(webhook_id=12345)
        with patch(_PATCH_RUN) as mock_run:
            await cog.on_message(msg)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_authorized_webhook(
        self,
        bot: MagicMock,
        runner: MagicMock,
        triggers: dict[str, WebhookTrigger],
    ) -> None:
        """Authorized webhooks are processed."""
        cog = WebhookTriggerCog(
            bot=bot,
            runner=runner,
            triggers=triggers,
            allowed_webhook_ids={12345},
        )
        msg = _make_message(webhook_id=12345)
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "session-123"
            await cog.on_message(msg)
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_wrong_channel(
        self,
        bot: MagicMock,
        runner: MagicMock,
        triggers: dict[str, WebhookTrigger],
    ) -> None:
        """Messages in other channels are ignored."""
        cog = WebhookTriggerCog(
            bot=bot,
            runner=runner,
            triggers=triggers,
            channel_ids={111},
        )
        msg = _make_message(channel_id=999)
        with patch(_PATCH_RUN) as mock_run:
            await cog.on_message(msg)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unmatched_prefix(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Unmatched prefixes are ignored."""
        msg = _make_message(content="Hello world")
        with patch(_PATCH_RUN) as mock_run:
            await cog.on_message(msg)
            mock_run.assert_not_called()


class TestTriggerExecution:
    """Test trigger execution logic."""

    @pytest.mark.asyncio
    async def test_matching_prefix_triggers_run(
        self,
        cog: WebhookTriggerCog,
        runner: MagicMock,
    ) -> None:
        """A matching prefix should trigger Claude Code execution."""
        msg = _make_message(content="🔄 docs-sync")
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "session-abc"
            await cog.on_message(msg)

            mock_run.assert_called_once()
            config = mock_run.call_args[0][0]  # RunConfig object
            assert config.prompt == "Sync docs"
            assert config.repo is None
            assert config.session_id is None

    @pytest.mark.asyncio
    async def test_creates_thread(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Trigger execution should create a Discord thread."""
        msg = _make_message(content="🔄 docs-sync")
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "session-abc"
            await cog.on_message(msg)
            msg.create_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_reaction(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Successful execution should add check reaction."""
        msg = _make_message(content="🔄 docs-sync")
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "session-abc"
            await cog.on_message(msg)
            msg.add_reaction.assert_called_with("✅")

    @pytest.mark.asyncio
    async def test_failure_reaction(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Failed execution should add error reaction."""
        msg = _make_message(content="🔄 docs-sync")
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            await cog.on_message(msg)
            msg.add_reaction.assert_called_with("❌")

    @pytest.mark.asyncio
    async def test_runner_clone_overrides(
        self,
        cog: WebhookTriggerCog,
        runner: MagicMock,
    ) -> None:
        """Trigger config should override cloned runner settings."""
        msg = _make_message(content="🔄 docs-sync")
        cloned = runner.clone.return_value
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "session-abc"
            await cog.on_message(msg)

            runner.clone.assert_called_once()
            assert cloned.dangerously_skip_permissions is True
            assert cloned.timeout_seconds == 600
            assert cloned.working_dir == "/home/user/project"

    @pytest.mark.asyncio
    async def test_prefix_starts_with_matching(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Prefix matching works with startswith."""
        msg = _make_message(content="🔄 docs-sync extra info")
        with patch(_PATCH_RUN, new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "session-abc"
            await cog.on_message(msg)
            mock_run.assert_called_once()


class TestConcurrency:
    """Test concurrent execution prevention."""

    @pytest.mark.asyncio
    async def test_concurrent_same_prefix_blocked(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Concurrent runs of same prefix should be blocked."""
        lock = cog._locks["🔄 docs-sync"]
        msg = _make_message(content="🔄 docs-sync")

        await lock.acquire()
        try:
            with patch(_PATCH_RUN) as mock_run:
                await cog.on_message(msg)
                mock_run.assert_not_called()
                msg.reply.assert_called_once()
                assert "already running" in msg.reply.call_args[0][0]
        finally:
            lock.release()

    @pytest.mark.asyncio
    async def test_different_prefix_not_blocked(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """Different prefixes should have independent locks."""
        lock = cog._locks["🔄 docs-sync"]
        msg = _make_message(content="🔄 deploy")

        await lock.acquire()
        try:
            with patch(
                _PATCH_RUN,
                new_callable=AsyncMock,
            ) as mock_run:
                mock_run.return_value = "session-abc"
                await cog.on_message(msg)
                mock_run.assert_called_once()
        finally:
            lock.release()


class TestActiveCount:
    """Test active_count tracking for drain coordination."""

    def test_initial_count_is_zero(self, cog: WebhookTriggerCog) -> None:
        assert cog.active_count == 0

    @pytest.mark.asyncio
    async def test_count_increments_during_execution(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """active_count should be 1 during execution and 0 after."""
        msg = _make_message(content="🔄 docs-sync")
        observed_counts: list[int] = []

        async def fake_run(config: object) -> str:  # receives RunConfig
            observed_counts.append(cog.active_count)
            return "session-abc"

        with patch(_PATCH_RUN, side_effect=fake_run):
            await cog.on_message(msg)

        assert observed_counts == [1]
        assert cog.active_count == 0

    @pytest.mark.asyncio
    async def test_count_decrements_on_failure(
        self,
        cog: WebhookTriggerCog,
    ) -> None:
        """active_count should decrement even if run_claude_in_thread raises."""
        msg = _make_message(content="🔄 docs-sync")

        with (
            patch(_PATCH_RUN, side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await cog._execute_trigger(
                msg,
                "🔄 docs-sync",
                cog.triggers["🔄 docs-sync"],
            )

        assert cog.active_count == 0


class TestWebhookTriggerDataclass:
    """Test WebhookTrigger dataclass."""

    def test_defaults(self) -> None:
        trigger = WebhookTrigger(prompt="test")
        assert trigger.prompt == "test"
        assert trigger.working_dir is None
        assert trigger.timeout == 300
        assert trigger.allowed_tools is None
        assert trigger.dangerously_skip_permissions is True

    def test_frozen(self) -> None:
        trigger = WebhookTrigger(prompt="test")
        with pytest.raises(AttributeError):
            trigger.prompt = "changed"  # type: ignore[misc]
