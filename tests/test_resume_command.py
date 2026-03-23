"""Tests for /resume command and ResumeSelectView."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from claude_discord.database.repository import SessionRecord


def _make_record(
    thread_id: int = 100,
    session_id: str = "abc-123",
    origin: str = "discord",
    summary: str | None = "Fix login bug",
    working_dir: str | None = "/home/user/project",
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


def _make_interaction(*, in_thread: bool = False) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    if in_thread:
        interaction.channel = MagicMock(spec=discord.Thread)
    else:
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.id = 999
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_cog():
    from claude_discord.cogs.session_manage import SessionManageCog

    bot = MagicMock()
    bot.channel_id = 999
    bot.get_channel = MagicMock(return_value=MagicMock(spec=discord.TextChannel))
    bot.get_cog = MagicMock(return_value=None)
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])
    repo.get_by_session_id = AsyncMock(return_value=None)
    return SessionManageCog(bot=bot, repo=repo)


class TestResumeCommand:
    """Tests for /resume slash command."""

    async def test_no_sessions_sends_ephemeral(self):
        """When no sessions exist, /resume shows an ephemeral message."""
        cog = _make_cog()
        cog.repo.list_all = AsyncMock(return_value=[])
        interaction = _make_interaction()
        await cog.resume_session.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

    async def test_shows_select_menu_with_sessions(self):
        """When sessions exist, /resume shows a select menu."""
        cog = _make_cog()
        records = [
            _make_record(thread_id=100, session_id="aaa-111", summary="First task"),
            _make_record(thread_id=101, session_id="bbb-222", summary="Second task"),
        ]
        cog.repo.list_all = AsyncMock(return_value=records)
        interaction = _make_interaction()
        await cog.resume_session.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        # Should have a view attached
        assert call_args.kwargs.get("view") is not None

    async def test_sessions_limited_to_25(self):
        """Select menu options are capped at 25 (Discord limit)."""
        cog = _make_cog()
        records = [
            _make_record(thread_id=i, session_id=f"sess-{i:03d}", summary=f"Task {i}")
            for i in range(30)
        ]
        cog.repo.list_all = AsyncMock(return_value=records)
        interaction = _make_interaction()
        await cog.resume_session.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        view = call_args.kwargs.get("view")
        assert view is not None
        # Find the select menu in the view's children
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert len(selects) == 1
        assert len(selects[0].options) <= 25


class TestResumeSelectView:
    """Tests for ResumeSelectView."""

    async def test_creates_options_from_records(self):
        from claude_discord.discord_ui.views import ResumeSelectView

        records = [
            _make_record(session_id="aaa-111", summary="First task"),
            _make_record(session_id="bbb-222", summary="Second task", working_dir="/tmp"),
        ]
        view = ResumeSelectView(
            records=records,
            bot=MagicMock(),
        )
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert len(selects) == 1
        assert len(selects[0].options) == 2

    async def test_option_labels_contain_summary(self):
        from claude_discord.discord_ui.views import ResumeSelectView

        records = [
            _make_record(session_id="aaa-111", summary="My cool task"),
        ]
        view = ResumeSelectView(records=records, bot=MagicMock())
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert "My cool task" in selects[0].options[0].label

    async def test_option_value_is_index(self):
        from claude_discord.discord_ui.views import ResumeSelectView

        records = [
            _make_record(session_id="aaa-111", summary="First"),
            _make_record(session_id="bbb-222", summary="Second"),
        ]
        view = ResumeSelectView(records=records, bot=MagicMock())
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert selects[0].options[0].value == "0"
        assert selects[0].options[1].value == "1"

    async def test_no_summary_shows_fallback(self):
        from claude_discord.discord_ui.views import ResumeSelectView

        records = [
            _make_record(session_id="aaa-111", summary=None),
        ]
        view = ResumeSelectView(records=records, bot=MagicMock())
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert selects[0].options[0].label != ""

    async def test_description_contains_working_dir(self):
        from claude_discord.discord_ui.views import ResumeSelectView

        records = [
            _make_record(session_id="aaa-111", summary="Task", working_dir="/home/user/myproject"),
        ]
        view = ResumeSelectView(records=records, bot=MagicMock())
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert "myproject" in (selects[0].options[0].description or "")
