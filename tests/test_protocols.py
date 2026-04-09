"""Tests for DrainAware protocol."""

from __future__ import annotations

from unittest.mock import MagicMock

from claude_discord.claude.runner import ClaudeRunner
from claude_discord.codex.runner import CodexRunner
from claude_discord.cogs.claude_chat import ClaudeChatCog
from claude_discord.cogs.webhook_trigger import WebhookTriggerCog
from claude_discord.protocols import AgentRunner, DrainAware


class TestDrainAwareProtocol:
    """DrainAware is a runtime_checkable Protocol — isinstance checks work."""

    def test_claude_chat_cog_satisfies_protocol(self) -> None:
        bot = MagicMock()
        bot.channel_id = 999
        cog = ClaudeChatCog(
            bot=bot,
            repo=MagicMock(),
            runner=MagicMock(spec=ClaudeRunner),
        )
        assert isinstance(cog, DrainAware)

    def test_webhook_trigger_cog_satisfies_protocol(self) -> None:
        cog = WebhookTriggerCog(
            bot=MagicMock(),
            runner=MagicMock(spec=ClaudeRunner),
            triggers={},
        )
        assert isinstance(cog, DrainAware)

    def test_plain_object_without_active_count_fails(self) -> None:
        """A plain object without active_count should not satisfy DrainAware."""

        class NoCog:
            pass

        assert not isinstance(NoCog(), DrainAware)

    def test_object_with_active_count_method_satisfies(self) -> None:
        """Any object with an active_count property satisfies DrainAware."""

        class CustomCog:
            @property
            def active_count(self) -> int:
                return 42

        assert isinstance(CustomCog(), DrainAware)


class TestAgentRunnerProtocol:
    """AgentRunner is the shared runner contract for backend-specific CLIs."""

    def test_claude_runner_satisfies_protocol(self) -> None:
        assert isinstance(ClaudeRunner(), AgentRunner)

    def test_codex_runner_satisfies_protocol(self) -> None:
        assert isinstance(CodexRunner(), AgentRunner)
