"""Tests for ClaudeChatCog: /stop command and attachment handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs.claude_chat import (
    _MAX_ATTACHMENT_BYTES,
    _MAX_ATTACHMENTS,
    _MAX_TOTAL_BYTES,
    ClaudeChatCog,
)
from claude_discord.concurrency import SessionRegistry
from claude_discord.coordination.service import CoordinationService


def _make_cog() -> ClaudeChatCog:
    """Return a ClaudeChatCog with minimal mocked dependencies."""
    bot = MagicMock()
    bot.channel_id = 999
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    repo.delete = AsyncMock(return_value=True)
    runner = MagicMock()
    runner.clone = MagicMock(return_value=MagicMock())
    return ClaudeChatCog(bot=bot, repo=repo, runner=runner)


def _make_thread_interaction(thread_id: int = 12345) -> MagicMock:
    """Return an Interaction whose channel is a discord.Thread."""
    interaction = MagicMock(spec=discord.Interaction)
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    interaction.channel = thread
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_channel_interaction() -> MagicMock:
    """Return an Interaction whose channel is NOT a thread."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


class TestStopCommand:
    @pytest.mark.asyncio
    async def test_stop_outside_thread_sends_ephemeral(self) -> None:
        """Using /stop outside a thread sends an ephemeral error."""
        cog = _make_cog()
        interaction = _make_channel_interaction()

        await cog.stop_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_stop_no_active_runner_sends_ephemeral(self) -> None:
        """Using /stop when nothing is running sends an ephemeral notice."""
        cog = _make_cog()
        interaction = _make_thread_interaction(thread_id=12345)

        # _active_runners is empty — no session running
        await cog.stop_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_stop_calls_runner_interrupt(self) -> None:
        """Using /stop with an active runner calls runner.interrupt()."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        mock_runner.interrupt.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_does_not_delete_session_from_db(self) -> None:
        """/stop must NOT delete the session from the DB (so resume works)."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        # repo.delete should NEVER be called by /stop
        cog.repo.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_does_not_remove_from_active_runners(self) -> None:
        """/stop should leave _active_runners cleanup to _run_claude's finally."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        # Still in dict — _run_claude's finally handles removal
        assert thread_id in cog._active_runners

    @pytest.mark.asyncio
    async def test_stop_sends_stopped_embed(self) -> None:
        """/stop success response should use the stopped_embed (orange, not red)."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        embed = call_kwargs.get("embed")
        assert embed is not None
        assert "stopped" in embed.title.lower()
        # Orange color (not red error)
        assert embed.color.value == 0xFFA500


class TestActiveCountAlias:
    """Tests for ClaudeChatCog.active_count (DrainAware alias)."""

    def test_active_count_equals_active_session_count(self) -> None:
        """active_count should be an alias for active_session_count."""
        cog = _make_cog()
        assert cog.active_count == 0
        assert cog.active_count == cog.active_session_count

        # Add a fake runner
        cog._active_runners[1] = MagicMock()
        assert cog.active_count == 1
        assert cog.active_count == cog.active_session_count

        cog._active_runners[2] = MagicMock()
        assert cog.active_count == 2
        assert cog.active_count == cog.active_session_count


class TestBuildPrompt:
    """Tests for the _build_prompt method (attachment handling)."""

    @staticmethod
    def _make_attachment(
        filename: str = "test.txt",
        content_type: str = "text/plain",
        size: int = 100,
        content: bytes = b"hello world",
    ) -> MagicMock:
        att = MagicMock(spec=discord.Attachment)
        att.filename = filename
        att.content_type = content_type
        att.size = size
        att.read = AsyncMock(return_value=content)
        return att

    @staticmethod
    def _make_message(content: str = "my message", attachments: list | None = None) -> MagicMock:
        msg = MagicMock(spec=discord.Message)
        msg.content = content
        msg.attachments = attachments or []
        return msg

    @pytest.mark.asyncio
    async def test_no_attachments_returns_content(self) -> None:
        cog = _make_cog()
        msg = self._make_message(content="hello")
        result = await cog._build_prompt(msg)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_text_attachment_appended(self) -> None:
        cog = _make_cog()
        att = self._make_attachment(filename="notes.txt", content=b"file content here")
        msg = self._make_message(content="check this", attachments=[att])

        result = await cog._build_prompt(msg)

        assert "check this" in result
        assert "notes.txt" in result
        assert "file content here" in result

    @pytest.mark.asyncio
    async def test_binary_attachment_skipped(self) -> None:
        cog = _make_cog()
        att = self._make_attachment(
            filename="image.png",
            content_type="image/png",
            content=b"\x89PNG...",
        )
        msg = self._make_message(content="see image", attachments=[att])

        result = await cog._build_prompt(msg)

        assert result == "see image"
        att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_oversized_attachment_skipped(self) -> None:
        cog = _make_cog()
        att = self._make_attachment(
            filename="huge.txt",
            content_type="text/plain",
            size=_MAX_ATTACHMENT_BYTES + 1,
        )
        msg = self._make_message(content="big file", attachments=[att])

        result = await cog._build_prompt(msg)

        assert result == "big file"
        att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_content_with_attachment(self) -> None:
        """Message with only an attachment (no text) should still work."""
        cog = _make_cog()
        att = self._make_attachment(
            filename="code.py", content_type="text/x-python", content=b"print('hi')"
        )
        msg = self._make_message(content="", attachments=[att])

        result = await cog._build_prompt(msg)

        assert "code.py" in result
        assert "print('hi')" in result

    @pytest.mark.asyncio
    async def test_max_attachments_limit(self) -> None:
        """Only the first _MAX_ATTACHMENTS files should be processed."""
        cog = _make_cog()
        attachments = [
            self._make_attachment(filename=f"file{i}.txt", content=f"content{i}".encode())
            for i in range(_MAX_ATTACHMENTS + 2)
        ]
        msg = self._make_message(attachments=attachments)

        await cog._build_prompt(msg)

        # Extra attachments beyond the limit should not be read
        for att in attachments[_MAX_ATTACHMENTS:]:
            att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_total_size_limit_stops_processing(self) -> None:
        """Processing stops when cumulative size exceeds _MAX_TOTAL_BYTES."""
        cog = _make_cog()
        # Each file is just under the per-file limit but together they exceed total
        chunk = _MAX_ATTACHMENT_BYTES - 100  # 49.9 KB
        attachments = [
            self._make_attachment(
                filename=f"file{i}.txt",
                size=chunk,
                content=b"x" * chunk,
            )
            for i in range(10)
        ]
        msg = self._make_message(attachments=attachments)

        await cog._build_prompt(msg)

        # Should stop after total exceeds _MAX_TOTAL_BYTES (~2 files)
        read_count = sum(1 for att in attachments if att.read.called)
        expected_max = (_MAX_TOTAL_BYTES // chunk) + 1
        assert read_count <= expected_max

    @pytest.mark.asyncio
    async def test_json_attachment_included(self) -> None:
        """application/json is in the allowed types."""
        cog = _make_cog()
        att = self._make_attachment(
            filename="config.json",
            content_type="application/json",
            content=b'{"key": "value"}',
        )
        msg = self._make_message(content="here is config", attachments=[att])

        result = await cog._build_prompt(msg)

        assert "config.json" in result
        assert '{"key": "value"}' in result

    @pytest.mark.asyncio
    async def test_multiple_text_attachments(self) -> None:
        """Multiple allowed attachments should all be included."""
        cog = _make_cog()
        attachments = [
            self._make_attachment(filename="a.txt", content=b"alpha"),
            self._make_attachment(filename="b.md", content_type="text/markdown", content=b"beta"),
        ]
        msg = self._make_message(content="two files", attachments=attachments)

        result = await cog._build_prompt(msg)

        assert "a.txt" in result
        assert "alpha" in result
        assert "b.md" in result
        assert "beta" in result


class TestRegistryAutoDiscovery:
    """Registry should be auto-discovered from bot.session_registry."""

    def test_auto_discovers_from_bot(self) -> None:
        """When registry=None, Cog picks up bot.session_registry."""
        bot = MagicMock()
        bot.session_registry = SessionRegistry()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._registry is bot.session_registry

    def test_explicit_registry_takes_precedence(self) -> None:
        """When registry is explicitly passed, it wins over bot attribute."""
        bot = MagicMock()
        bot.session_registry = SessionRegistry()
        explicit = SessionRegistry()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), registry=explicit)
        assert cog._registry is explicit

    def test_no_bot_attribute_falls_back_to_none(self) -> None:
        """When bot has no session_registry, _registry stays None."""
        bot = MagicMock(spec=[])  # no attributes
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._registry is None


class TestZeroConfigCoordination:
    """_get_coordination() must work without any consumer wiring (Zero-Config Principle).

    Consumers (like EbiBot) must get new features by updating the package alone —
    no code changes, no bot.coordination wiring required.
    """

    def test_auto_creates_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No bot.coordination → auto-creates CoordinationService from env var."""
        monkeypatch.setenv("COORDINATION_CHANNEL_ID", "1234567890")
        bot = MagicMock(spec=[])  # no attributes at all
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        svc = cog._get_coordination()
        assert isinstance(svc, CoordinationService)
        assert svc.enabled is True

    def test_no_op_when_env_var_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env var → returns a no-op CoordinationService (never None)."""
        monkeypatch.delenv("COORDINATION_CHANNEL_ID", raising=False)
        bot = MagicMock(spec=[])
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        svc = cog._get_coordination()
        assert isinstance(svc, CoordinationService)
        assert svc.enabled is False  # no-op, but not None

    def test_bot_attribute_takes_precedence(self) -> None:
        """Explicitly set bot.coordination wins over env var auto-creation."""
        explicit = CoordinationService(MagicMock(), channel_id=9999)
        bot = MagicMock()
        bot.coordination = explicit
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._get_coordination() is explicit

    def test_constructor_arg_takes_precedence(self) -> None:
        """Explicitly passed coordination= wins over everything."""
        explicit = CoordinationService(MagicMock(), channel_id=9999)
        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), coordination=explicit)
        assert cog._get_coordination() is explicit

    def test_result_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Second call returns same object (no repeated env var reads)."""
        monkeypatch.setenv("COORDINATION_CHANNEL_ID", "1234567890")
        bot = MagicMock(spec=[])
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._get_coordination() is cog._get_coordination()


class TestSpawnSession:
    """Tests for ClaudeChatCog.spawn_session()."""

    @pytest.mark.asyncio
    async def test_spawn_creates_thread_and_returns_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """spawn_session creates a thread with the right name and returns it."""
        import discord
        from unittest.mock import AsyncMock, MagicMock, patch

        thread = MagicMock(spec=discord.Thread)
        thread.id = 42
        thread.name = "Test spawn"
        thread.send = AsyncMock()

        channel = MagicMock()
        channel.create_thread = AsyncMock(return_value=thread)

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())

        with patch.object(cog, "_run_claude", new=AsyncMock()) as mock_run:
            result = await cog.spawn_session(channel, "Do the thing")

        assert result is thread
        channel.create_thread.assert_called_once()
        call_kwargs = channel.create_thread.call_args.kwargs
        assert call_kwargs["name"] == "Do the thing"
        assert call_kwargs["type"] == discord.ChannelType.public_thread

    @pytest.mark.asyncio
    async def test_spawn_uses_custom_thread_name(self) -> None:
        """thread_name overrides the default (prompt[:100])."""
        import discord
        from unittest.mock import AsyncMock, MagicMock, patch

        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        channel = MagicMock()
        channel.create_thread = AsyncMock(return_value=thread)

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())

        with patch.object(cog, "_run_claude", new=AsyncMock()):
            await cog.spawn_session(channel, "Very long prompt text", thread_name="Short name")

        kwargs = channel.create_thread.call_args.kwargs
        assert kwargs["name"] == "Short name"

    @pytest.mark.asyncio
    async def test_spawn_posts_seed_message(self) -> None:
        """spawn_session sends the prompt as the first thread message."""
        import discord
        from unittest.mock import AsyncMock, MagicMock, patch

        thread = MagicMock(spec=discord.Thread)
        seed_msg = MagicMock()
        thread.send = AsyncMock(return_value=seed_msg)

        channel = MagicMock()
        channel.create_thread = AsyncMock(return_value=thread)

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())

        with patch.object(cog, "_run_claude", new=AsyncMock()) as mock_run:
            await cog.spawn_session(channel, "Hello Claude")

        thread.send.assert_called_once_with("Hello Claude")
        # _run_claude receives the seed message (not a user message)
        user_msg_arg = mock_run.call_args.args[0]
        assert user_msg_arg is seed_msg
