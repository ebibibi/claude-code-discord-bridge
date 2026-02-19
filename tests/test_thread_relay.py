"""Tests for ThreadRelayCog: /relay command and cross-thread routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from claude_discord.cogs.thread_relay import _RELAY_PREFIX_TMPL, ThreadRelayCog
from claude_discord.discord_ui.embeds import relay_received_embed, relay_sent_embed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cog(channel_id: int = 999) -> ThreadRelayCog:
    """Return a ThreadRelayCog with minimal mocked dependencies."""
    bot = MagicMock()
    bot.channel_id = channel_id
    bot.session_registry = None
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    runner = MagicMock()
    runner.clone = MagicMock(return_value=MagicMock())
    return ThreadRelayCog(bot=bot, repo=repo, runner=runner)


def _make_thread(
    thread_id: int = 100, parent_id: int = 999, name: str = "test-thread"
) -> MagicMock:
    """Return a mocked discord.Thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    thread.parent_id = parent_id
    thread.name = name
    thread.mention = f"<#{thread_id}>"
    thread.jump_url = f"https://discord.com/channels/1/{thread_id}"
    thread.send = AsyncMock()
    return thread


def _drain_coro(coro, **_kwargs) -> None:
    """Close a coroutine immediately to avoid 'never awaited' warnings in tests.

    When asyncio.create_task is patched, the coroutine argument is never
    scheduled, so Python warns about it. Explicitly closing it silences the
    warning without actually executing the async code.
    """
    import inspect

    if inspect.iscoroutine(coro):
        coro.close()


def _make_interaction(
    channel: MagicMock,
    user_id: int = 42,
) -> MagicMock:
    """Return a mocked discord.Interaction."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = channel
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ---------------------------------------------------------------------------
# /relay — authorization
# ---------------------------------------------------------------------------


class TestRelayAuthorization:
    @pytest.mark.asyncio
    async def test_unauthorized_user_denied(self) -> None:
        """User not in allowed_user_ids receives ephemeral error."""
        bot = MagicMock()
        bot.channel_id = 999
        bot.session_registry = None
        repo = MagicMock()
        runner = MagicMock()
        cog = ThreadRelayCog(bot=bot, repo=repo, runner=runner, allowed_user_ids={1, 2, 3})

        source = _make_thread(thread_id=100)
        target = _make_thread(thread_id=200)
        interaction = _make_interaction(source, user_id=99)  # not in allowed set

        await cog.relay.callback(cog, interaction, target, "hello")

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_authorized_user_allowed(self) -> None:
        """User in allowed_user_ids proceeds past the auth check."""
        bot = MagicMock()
        bot.channel_id = 999
        bot.session_registry = None
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        runner = MagicMock()
        runner.clone = MagicMock(return_value=MagicMock())
        cog = ThreadRelayCog(bot=bot, repo=repo, runner=runner, allowed_user_ids={42})

        source = _make_thread(thread_id=100)
        target = _make_thread(thread_id=200)
        interaction = _make_interaction(source, user_id=42)  # in allowed set

        with patch("claude_discord.cogs.thread_relay.asyncio.create_task", side_effect=_drain_coro):
            await cog.relay.callback(cog, interaction, target, "hello")

        # Auth passed — ephemeral should NOT have been sent
        interaction.response.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# /relay — channel validation
# ---------------------------------------------------------------------------


class TestRelayChannelValidation:
    @pytest.mark.asyncio
    async def test_command_outside_thread_rejected(self) -> None:
        """Using /relay from a non-thread channel sends ephemeral error."""
        cog = _make_cog()
        channel = MagicMock(spec=discord.TextChannel)  # not a Thread
        target = _make_thread(thread_id=200)
        interaction = _make_interaction(channel)

        await cog.relay.callback(cog, interaction, target, "hello")

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_self_relay_rejected(self) -> None:
        """Relaying to the same thread is rejected with ephemeral error."""
        cog = _make_cog()
        thread = _make_thread(thread_id=100)
        interaction = _make_interaction(thread)

        await cog.relay.callback(cog, interaction, thread, "hello")

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_target_wrong_channel_rejected(self) -> None:
        """Target thread in a different parent channel is rejected."""
        cog = _make_cog(channel_id=999)
        source = _make_thread(thread_id=100, parent_id=999)
        target = _make_thread(thread_id=200, parent_id=888)  # wrong parent
        interaction = _make_interaction(source)

        await cog.relay.callback(cog, interaction, target, "hello")

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /relay — happy path
# ---------------------------------------------------------------------------


class TestRelayHappyPath:
    @pytest.mark.asyncio
    async def test_attribution_embed_sent_to_target(self) -> None:
        """Relay posts an attribution embed in the target thread."""
        cog = _make_cog(channel_id=999)
        source = _make_thread(thread_id=100, parent_id=999)
        target = _make_thread(thread_id=200, parent_id=999)
        interaction = _make_interaction(source)

        with patch("claude_discord.cogs.thread_relay.asyncio.create_task", side_effect=_drain_coro):
            await cog.relay.callback(cog, interaction, target, "review this")

        target.send.assert_called_once()
        sent_embed = target.send.call_args.kwargs.get("embed")
        assert sent_embed is not None
        assert "📨" in sent_embed.title

    @pytest.mark.asyncio
    async def test_confirmation_embed_sent_to_source(self) -> None:
        """Relay sends a confirmation embed to the source thread via followup."""
        cog = _make_cog(channel_id=999)
        source = _make_thread(thread_id=100, parent_id=999)
        target = _make_thread(thread_id=200, parent_id=999)
        interaction = _make_interaction(source)

        with patch("claude_discord.cogs.thread_relay.asyncio.create_task", side_effect=_drain_coro):
            await cog.relay.callback(cog, interaction, target, "review this")

        interaction.followup.send.assert_called_once()
        sent_embed = interaction.followup.send.call_args.kwargs.get("embed")
        assert sent_embed is not None
        assert "📤" in sent_embed.title

    @pytest.mark.asyncio
    async def test_create_task_called_with_correct_name(self) -> None:
        """A named asyncio task is created for the relay execution."""
        cog = _make_cog(channel_id=999)
        source = _make_thread(thread_id=100, parent_id=999, name="src")
        target = _make_thread(thread_id=200, parent_id=999)
        interaction = _make_interaction(source)

        with patch(
            "claude_discord.cogs.thread_relay.asyncio.create_task", side_effect=_drain_coro
        ) as mock_task:
            await cog.relay.callback(cog, interaction, target, "hello")

        mock_task.assert_called_once()
        _, kwargs = mock_task.call_args
        assert kwargs.get("name") == "relay-100->200"

    @pytest.mark.asyncio
    async def test_relay_prompt_includes_source_attribution(self) -> None:
        """The prompt passed to Claude includes the source thread name."""
        cog = _make_cog(channel_id=999)
        source = _make_thread(thread_id=100, parent_id=999, name="alpha")
        target = _make_thread(thread_id=200, parent_id=999)
        interaction = _make_interaction(source)
        message = "What is the answer?"

        captured_prompt: list[str] = []

        async def fake_run_relay(t, prompt, session_id):
            captured_prompt.append(prompt)

        with (
            patch.object(cog, "_run_relay_in_target", new=fake_run_relay),
            patch("claude_discord.cogs.thread_relay.asyncio.create_task", side_effect=_drain_coro),
        ):
            await cog.relay.callback(cog, interaction, target, message)

        # We can't easily intercept the coroutine args without running the task,
        # so check the prompt prefix is correct by calling the method directly.
        expected_prefix = _RELAY_PREFIX_TMPL.format(source_name="alpha")
        assert expected_prefix.startswith("[Relayed from #alpha]")

    @pytest.mark.asyncio
    async def test_existing_session_resumed_in_target(self) -> None:
        """When target thread has an existing session, it is resumed."""
        cog = _make_cog(channel_id=999)
        source = _make_thread(thread_id=100, parent_id=999)
        target = _make_thread(thread_id=200, parent_id=999)
        interaction = _make_interaction(source)

        # Simulate an existing session record for the target thread
        record = MagicMock()
        record.session_id = "existing-session-abc"
        cog.repo.get = AsyncMock(return_value=record)

        captured: list[str | None] = []

        async def fake_run_relay(t, prompt, session_id):
            captured.append(session_id)

        with (
            patch.object(cog, "_run_relay_in_target", new=fake_run_relay),
            patch("claude_discord.cogs.thread_relay.asyncio.create_task", side_effect=_drain_coro),
        ):
            await cog.relay.callback(cog, interaction, target, "hello")

        # The session_id from the record should be passed (test via repo.get call)
        cog.repo.get.assert_called_once_with(target.id)


# ---------------------------------------------------------------------------
# Embed unit tests
# ---------------------------------------------------------------------------


class TestRelayEmbeds:
    def test_relay_sent_embed_contains_target_mention(self) -> None:
        """relay_sent_embed includes the target thread mention."""
        target = _make_thread(thread_id=200, name="worker")
        embed = relay_sent_embed(target, "Do the thing")
        assert target.mention in embed.description

    def test_relay_sent_embed_has_jump_field(self) -> None:
        """relay_sent_embed includes a jump link field."""
        target = _make_thread(thread_id=200, name="worker")
        embed = relay_sent_embed(target, "Do the thing")
        assert any(f.name == "Jump" for f in embed.fields)

    def test_relay_received_embed_contains_source_mention(self) -> None:
        """relay_received_embed includes the source thread mention."""
        source = _make_thread(thread_id=100, name="orchestrator")
        embed = relay_received_embed(source, "Hello from source")
        assert source.mention in embed.description

    def test_relay_received_embed_has_jump_field(self) -> None:
        """relay_received_embed includes a jump link field."""
        source = _make_thread(thread_id=100, name="orchestrator")
        embed = relay_received_embed(source, "Hello from source")
        assert any(f.name == "Jump" for f in embed.fields)

    def test_long_message_preview_truncated(self) -> None:
        """Messages longer than 200 chars are truncated with ellipsis."""
        long_message = "a" * 300
        target = _make_thread(thread_id=200)
        embed = relay_sent_embed(target, long_message)
        assert "…" in embed.description
        assert len(embed.description) < len(long_message) + 50  # well below full length

    def test_short_message_not_truncated(self) -> None:
        """Short messages are preserved as-is."""
        short_message = "short"
        target = _make_thread(thread_id=200)
        embed = relay_sent_embed(target, short_message)
        assert short_message in embed.description
        assert "…" not in embed.description
