"""Tests for /rewind and /fork slash commands.

/rewind — Reset conversation history while preserving working files.
/fork   — Create a new thread continuing this conversation from the same point.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from claude_discord.cogs.claude_chat import ClaudeChatCog
from claude_discord.database.repository import SessionRecord


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
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_channel_interaction() -> MagicMock:
    """Return an Interaction whose channel is NOT a thread."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_session_record(
    thread_id: int = 12345,
    session_id: str = "sess-abc",
    working_dir: str | None = "/tmp/work",
) -> SessionRecord:
    return SessionRecord(
        thread_id=thread_id,
        session_id=session_id,
        working_dir=working_dir,
        model=None,
        origin="discord",
        summary=None,
        created_at="2026-01-01 00:00:00",
        last_used_at="2026-01-01 00:00:00",
    )


# ---------------------------------------------------------------------------
# /rewind
# ---------------------------------------------------------------------------


class TestRewindCommand:
    @pytest.mark.asyncio
    async def test_rewind_outside_thread_sends_ephemeral(self) -> None:
        """Using /rewind outside a thread shows an ephemeral error."""
        cog = _make_cog()
        interaction = _make_channel_interaction()

        await cog.rewind_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_rewind_no_session_sends_ephemeral(self) -> None:
        """Using /rewind when no session exists shows an ephemeral notice."""
        cog = _make_cog()
        cog.repo.get = AsyncMock(return_value=None)
        cog.repo.delete = AsyncMock(return_value=False)
        interaction = _make_thread_interaction()

        await cog.rewind_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_rewind_deletes_session_from_db(self) -> None:
        """/rewind must delete the session from the DB to clear conversation."""
        cog = _make_cog()
        thread_id = 12345
        cog.repo.get = AsyncMock(return_value=_make_session_record(thread_id))
        cog.repo.delete = AsyncMock(return_value=True)
        interaction = _make_thread_interaction(thread_id=thread_id)

        await cog.rewind_session.callback(cog, interaction)

        cog.repo.delete.assert_called_once_with(thread_id)

    @pytest.mark.asyncio
    async def test_rewind_kills_active_runner(self) -> None:
        """/rewind stops any currently running Claude process."""
        cog = _make_cog()
        thread_id = 12345
        cog.repo.get = AsyncMock(return_value=_make_session_record(thread_id))
        cog.repo.delete = AsyncMock(return_value=True)
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.kill = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.rewind_session.callback(cog, interaction)

        mock_runner.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_rewind_removes_runner_from_active_dict(self) -> None:
        """/rewind removes the runner from _active_runners after killing it."""
        cog = _make_cog()
        thread_id = 12345
        cog.repo.get = AsyncMock(return_value=_make_session_record(thread_id))
        cog.repo.delete = AsyncMock(return_value=True)
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.kill = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.rewind_session.callback(cog, interaction)

        assert thread_id not in cog._active_runners

    @pytest.mark.asyncio
    async def test_rewind_sends_confirmation_message(self) -> None:
        """/rewind sends a visible (non-ephemeral) confirmation message."""
        cog = _make_cog()
        thread_id = 12345
        cog.repo.get = AsyncMock(return_value=_make_session_record(thread_id))
        cog.repo.delete = AsyncMock(return_value=True)
        interaction = _make_thread_interaction(thread_id=thread_id)

        await cog.rewind_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        # Must NOT be ephemeral — the rewind notice should be visible in the thread.
        assert not call_kwargs.get("ephemeral", False)

    @pytest.mark.asyncio
    async def test_rewind_confirmation_mentions_files_preserved(self) -> None:
        """The confirmation message must convey that working files are kept."""
        cog = _make_cog()
        thread_id = 12345
        cog.repo.get = AsyncMock(return_value=_make_session_record(thread_id))
        cog.repo.delete = AsyncMock(return_value=True)
        interaction = _make_thread_interaction(thread_id=thread_id)

        await cog.rewind_session.callback(cog, interaction)

        content: str = interaction.response.send_message.call_args.args[0]
        # The message should mention files are preserved so users understand what changed.
        assert any(
            word in content.lower() for word in ("file", "work", "保持", "preserved", "kept")
        )


# ---------------------------------------------------------------------------
# /fork
# ---------------------------------------------------------------------------


class TestForkCommand:
    @pytest.mark.asyncio
    async def test_fork_outside_thread_sends_ephemeral(self) -> None:
        """Using /fork outside a thread shows an ephemeral error."""
        cog = _make_cog()
        interaction = _make_channel_interaction()

        await cog.fork_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_fork_no_session_sends_ephemeral(self) -> None:
        """Using /fork when no session exists shows an ephemeral error."""
        cog = _make_cog()
        cog.repo.get = AsyncMock(return_value=None)
        interaction = _make_thread_interaction()

        await cog.fork_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_fork_creates_new_thread(self) -> None:
        """/fork creates a new Discord thread in the parent channel."""
        cog = _make_cog()
        thread_id = 12345
        session_id = "sess-abc"
        record = _make_session_record(thread_id=thread_id, session_id=session_id)
        cog.repo.get = AsyncMock(return_value=record)

        interaction = _make_thread_interaction(thread_id=thread_id)
        parent_channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.parent = parent_channel

        new_thread = MagicMock(spec=discord.Thread)
        new_thread.id = 99999
        new_thread.mention = "<#99999>"

        with patch.object(
            cog, "spawn_session", new=AsyncMock(return_value=new_thread)
        ) as mock_spawn:
            await cog.fork_session.callback(cog, interaction)

        mock_spawn.assert_called_once()

    @pytest.mark.asyncio
    async def test_fork_uses_same_session_id(self) -> None:
        """/fork passes the current session_id to spawn_session for conversation continuity."""
        cog = _make_cog()
        thread_id = 12345
        session_id = "sess-abc"
        record = _make_session_record(thread_id=thread_id, session_id=session_id)
        cog.repo.get = AsyncMock(return_value=record)

        interaction = _make_thread_interaction(thread_id=thread_id)
        parent_channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.parent = parent_channel

        new_thread = MagicMock(spec=discord.Thread)
        new_thread.id = 99999
        new_thread.mention = "<#99999>"

        with patch.object(
            cog, "spawn_session", new=AsyncMock(return_value=new_thread)
        ) as mock_spawn:
            await cog.fork_session.callback(cog, interaction)

        call_kwargs = mock_spawn.call_args.kwargs
        assert call_kwargs.get("session_id") == session_id

    @pytest.mark.asyncio
    async def test_fork_sends_link_to_new_thread(self) -> None:
        """/fork replies with a link to the newly created thread."""
        cog = _make_cog()
        thread_id = 12345
        record = _make_session_record(thread_id=thread_id)
        cog.repo.get = AsyncMock(return_value=record)

        interaction = _make_thread_interaction(thread_id=thread_id)
        parent_channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.parent = parent_channel

        new_thread = MagicMock(spec=discord.Thread)
        new_thread.id = 99999
        new_thread.mention = "<#99999>"

        with patch.object(cog, "spawn_session", new=AsyncMock(return_value=new_thread)):
            await cog.fork_session.callback(cog, interaction)

        # /fork uses defer+followup so the fork link appears via followup.send.
        interaction.followup.send.assert_called_once()
        content: str = interaction.followup.send.call_args.args[0]
        # The reply should reference the new thread.
        assert "<#99999>" in content

    @pytest.mark.asyncio
    async def test_fork_no_parent_channel_sends_ephemeral(self) -> None:
        """/fork in a thread without a parent channel shows an ephemeral error.

        This can happen when the thread's parent channel is unavailable (e.g.
        a DM thread, or a thread the bot can't see).
        """
        cog = _make_cog()
        thread_id = 12345
        record = _make_session_record(thread_id=thread_id)
        cog.repo.get = AsyncMock(return_value=record)

        interaction = _make_thread_interaction(thread_id=thread_id)
        interaction.channel.parent = None  # No parent channel

        await cog.fork_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
