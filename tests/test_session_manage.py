"""Tests for SessionManageCog: /sessions, /resume-info, /sync-sessions commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from claude_discord.database.repository import SessionRecord


def _make_record(
    thread_id: int = 100,
    session_id: str = "abc-123",
    backend: str = "claude",
    origin: str = "discord",
    summary: str | None = "Fix login bug",
    working_dir: str | None = "/home/user",
    model: str | None = "sonnet",
    context_window: int | None = None,
    context_used: int | None = None,
) -> SessionRecord:
    return SessionRecord(
        thread_id=thread_id,
        session_id=session_id,
        working_dir=working_dir,
        model=model,
        origin=origin,
        summary=summary,
        context_window=context_window,
        context_used=context_used,
        created_at="2026-02-19 10:00:00",
        last_used_at="2026-02-19 11:00:00",
        backend=backend,
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


def _make_settings_repo(default_backend: str | None = None) -> MagicMock:
    settings_repo = MagicMock()

    async def _settings_get(key: str, *, default: str | None = None) -> str | None:
        if key == "default_backend":
            return default_backend
        return default

    settings_repo.get = AsyncMock(side_effect=_settings_get)
    settings_repo.set = AsyncMock()
    settings_repo.set_default_backend = AsyncMock(
        return_value=(default_backend or "claude")
    )
    settings_repo.delete = AsyncMock(return_value=default_backend is not None)
    return settings_repo


def _make_cog(
    *,
    settings_repo: MagicMock | None = None,
    default_backend: str = "claude",
):
    from claude_discord.cogs.session_manage import SessionManageCog

    bot = MagicMock()
    bot.channel_id = 999
    bot.default_backend = default_backend
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])
    repo.get_by_session_id = AsyncMock(return_value=None)
    return SessionManageCog(bot=bot, repo=repo, settings_repo=settings_repo)


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
        assert "claude --resume def-456" in embed.description

    async def test_shows_codex_resume_command(self):
        cog = _make_cog()
        record = _make_record(thread_id=555, session_id="rollout-123", backend="codex")
        cog.repo.get = AsyncMock(return_value=record)
        interaction = _make_thread_interaction(thread_id=555)
        await cog.resume_info.callback(cog, interaction)
        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "codex exec resume rollout-123" in embed.description


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


class TestBackendSettings:
    async def test_backend_show_uses_settings_override(self):
        cog = _make_cog(settings_repo=_make_settings_repo(default_backend="codex"))
        interaction = _make_channel_interaction()

        await cog.backend_show.callback(cog, interaction)

        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "codex" in embed.description.lower()
        assert "override" in embed.footer.text.lower()

    async def test_backend_show_falls_back_to_configured_default(self):
        cog = _make_cog(
            settings_repo=_make_settings_repo(default_backend=None),
            default_backend="codex",
        )
        interaction = _make_channel_interaction()

        await cog.backend_show.callback(cog, interaction)

        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "codex" in embed.description.lower()
        assert "fallback" in embed.footer.text.lower()

    async def test_backend_set_persists_setting(self):
        settings_repo = _make_settings_repo(default_backend=None)
        settings_repo.set_default_backend = AsyncMock(return_value="codex")
        cog = _make_cog(settings_repo=settings_repo)
        interaction = _make_channel_interaction()

        await cog.backend_set.callback(cog, interaction, backend="codex")

        settings_repo.set_default_backend.assert_awaited_once_with("codex")
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "codex" in embed.description.lower()

    async def test_backend_set_no_settings_repo(self):
        from claude_discord.cogs.session_manage import SessionManageCog

        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        cog = SessionManageCog(bot=bot, repo=repo)
        interaction = _make_channel_interaction()

        await cog.backend_set.callback(cog, interaction, backend="codex")

        call_args = interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True


class TestContextCommand:
    """Tests for /context slash command."""

    async def test_context_not_in_thread_returns_ephemeral(self):
        from claude_discord.cogs.session_manage import SessionManageCog

        bot = MagicMock()
        repo = MagicMock()
        cog = SessionManageCog(bot=bot, repo=repo)

        interaction = _make_channel_interaction()
        await cog.context_show.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs.get("ephemeral") is True

    async def test_context_no_stats_shows_info_message(self):
        from claude_discord.cogs.session_manage import SessionManageCog

        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_make_record(context_window=None, context_used=None))
        cog = SessionManageCog(bot=bot, repo=repo)

        interaction = _make_thread_interaction()
        await cog.context_show.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        msg = interaction.response.send_message.call_args
        # Should reply with ephemeral info (no embed with stats)
        assert msg.kwargs.get("ephemeral") is True

    async def test_context_shows_stats_embed(self):
        from claude_discord.cogs.session_manage import SessionManageCog

        bot = MagicMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_make_record(context_window=200000, context_used=134000))
        cog = SessionManageCog(bot=bot, repo=repo)

        interaction = _make_thread_interaction()
        await cog.context_show.callback(cog, interaction)

        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "67" in embed.description  # 134000/200000 = 67%


class TestUsageCommand:
    """Tests for /usage slash command."""

    async def test_usage_no_data_shows_info_message(self):
        from claude_discord.cogs.session_manage import SessionManageCog
        from claude_discord.database.repository import UsageStatsRepository

        bot = MagicMock()
        repo = MagicMock()
        usage_repo = MagicMock(spec=UsageStatsRepository)
        usage_repo.get_latest = AsyncMock(return_value=[])
        cog = SessionManageCog(bot=bot, repo=repo, usage_repo=usage_repo)

        interaction = _make_channel_interaction()
        await cog.usage_show.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs.get("ephemeral") is True

    async def test_usage_shows_stats_embed(self):
        import time

        from claude_discord.claude.types import RateLimitInfo
        from claude_discord.cogs.session_manage import SessionManageCog
        from claude_discord.database.repository import UsageStatsRepository

        bot = MagicMock()
        repo = MagicMock()
        usage_repo = MagicMock(spec=UsageStatsRepository)
        usage_repo.get_latest = AsyncMock(
            return_value=[
                RateLimitInfo(
                    rate_limit_type="five_hour",
                    status="allowed",
                    utilization=0.61,
                    resets_at=int(time.time()) + 7800,  # 2h 10m from now
                ),
            ]
        )
        cog = SessionManageCog(bot=bot, repo=repo, usage_repo=usage_repo)

        interaction = _make_channel_interaction()
        await cog.usage_show.callback(cog, interaction)

        call_args = interaction.response.send_message.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        # Should show utilization percentage
        assert "61" in embed.description
