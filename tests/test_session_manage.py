"""Tests for SessionManageCog: /sessions, /resume-info, /sync-sessions commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from claude_discord.database.repository import SessionRecord


def _make_record(
    thread_id: int = 100,
    session_id: str = "abc-123",
    origin: str = "discord",
    summary: str | None = "Fix login bug",
    working_dir: str | None = "/home/user",
    model: str | None = "sonnet",
) -> SessionRecord:
    return SessionRecord(
        thread_id=thread_id,
        session_id=session_id,
        working_dir=working_dir,
        model=model,
        origin=origin,
        summary=summary,
        created_at="2026-02-19 10:00:00",
        last_used_at="2026-02-19 11:00:00",
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


def _make_cog():
    from claude_discord.cogs.session_manage import SessionManageCog

    bot = MagicMock()
    bot.channel_id = 999
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])
    repo.get_by_session_id = AsyncMock(return_value=None)
    return SessionManageCog(bot=bot, repo=repo)


class TestResumeInfo:
    async def test_outside_thread_sends_ephemeral(self):
        cog = _make_cog()
        interaction = _make_channel_interaction()
        await cog.resume_info.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

    async def test_no_session_sends_ephemeral(self):
        cog = _make_cog()
        cog.repo.get = AsyncMock(return_value=None)
        interaction = _make_thread_interaction(thread_id=555)
        await cog.resume_info.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

    async def test_shows_resume_command(self):
        cog = _make_cog()
        record = _make_record(thread_id=555, session_id="def-456")
        cog.repo.get = AsyncMock(return_value=record)
        interaction = _make_thread_interaction(thread_id=555)
        await cog.resume_info.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        # Should contain an embed with the resume command
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "def-456" in embed.description


class TestSessionsList:
    async def test_empty_sessions(self):
        cog = _make_cog()
        cog.repo.list_all = AsyncMock(return_value=[])
        interaction = _make_channel_interaction()
        await cog.sessions_list.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        # Should send something indicating no sessions
        embed = call_args.kwargs.get("embed")
        assert embed is not None

    async def test_shows_sessions(self):
        cog = _make_cog()
        records = [
            _make_record(thread_id=100, session_id="aaa", origin="discord", summary="First task"),
            _make_record(thread_id=101, session_id="bbb", origin="cli", summary="CLI task"),
        ]
        cog.repo.list_all = AsyncMock(return_value=records)
        interaction = _make_channel_interaction()
        await cog.sessions_list.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert len(embed.fields) == 2

    async def test_session_origin_icons(self):
        cog = _make_cog()
        records = [
            _make_record(session_id="d1", origin="discord", summary="Discord session"),
            _make_record(session_id="c1", origin="cli", summary="CLI session", thread_id=101),
        ]
        cog.repo.list_all = AsyncMock(return_value=records)
        interaction = _make_channel_interaction()
        await cog.sessions_list.callback(cog, interaction)
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        # Discord sessions show 💬, CLI sessions show 🖥️
        assert "\U0001f4ac" in embed.fields[0].name  # 💬
        assert "\U0001f5a5" in embed.fields[1].name  # 🖥️
