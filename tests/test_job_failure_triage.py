"""tests/test_job_failure_triage.py

Unit tests for JobFailureTriageCog.

This Cog monitors the bot-notifications channel for scheduler job failure
embeds (sent via webhook) and auto-creates investigation threads with Claude.
"""

from __future__ import annotations

import os

# Set required env vars before the module under test is imported.
os.environ.setdefault("JOB_TRIAGE_CHANNEL_ID", "222222222222222222")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import discord  # noqa: E402
import pytest  # noqa: E402

from examples.ebibot.cogs.job_failure_triage import (  # noqa: E402
    JOB_TRIAGE_CHANNEL_ID,
    JobFailureTriageCog,
    _extract_failure_info,
)

_TEST_CHANNEL_ID: int = JOB_TRIAGE_CHANNEL_ID  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Embed creation helpers
# ---------------------------------------------------------------------------


def _make_failure_embed(
    title: str = "Job Failed",
    description: str = "**bluesky_youtube_post** が失敗しました",
    color: int = 0xFF0000,
    job_id: str = "bluesky_youtube_post",
    duration: str = "12.3s",
    schedule: str = "daily_post",
    error: str = "```\nHTTP 429: rate limit exceeded\n```",
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(name="Job ID", value=job_id, inline=True)
    embed.add_field(name="Duration", value=duration, inline=True)
    embed.add_field(name="Schedule", value=schedule, inline=True)
    embed.add_field(name="Error", value=error, inline=False)
    embed.set_footer(text="Scheduler v2.0")
    return embed


def _make_timeout_embed(
    job_name: str = "ai_full_maintenance",
    job_id: str = "ai_full_maintenance",
    timeout: str = "600s",
) -> discord.Embed:
    embed = discord.Embed(
        title="Job Timeout",
        description=f"**{job_name}** がタイムアウトしました",
        color=0xFFAA00,
    )
    embed.add_field(name="Job ID", value=job_id, inline=True)
    embed.add_field(name="Timeout", value=timeout, inline=True)
    embed.add_field(name="Schedule", value="daily_maintenance", inline=True)
    embed.set_footer(text="Scheduler v2.0")
    return embed


def _make_success_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Job Completed Successfully",
        description="**goodmorning_collect** が正常に完了しました",
        color=0x00FF00,
    )
    embed.set_footer(text="Scheduler v2.0")
    return embed


# ---------------------------------------------------------------------------
# Discord mock helpers
# ---------------------------------------------------------------------------


def _make_text_channel(channel_id: int) -> MagicMock:
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    return ch


def _make_message(
    embeds: list[discord.Embed] | None = None,
    content: str = "",
    channel_id: int = _TEST_CHANNEL_ID,
    webhook_id: int | None = 123456789,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.id = 55555
    msg.embeds = embeds or []
    msg.webhook_id = webhook_id
    msg.author = MagicMock()
    msg.channel = _make_text_channel(channel_id)
    mock_thread = AsyncMock(spec=discord.Thread)
    mock_thread.id = 99999
    mock_thread.send = AsyncMock()
    msg.create_thread = AsyncMock(return_value=mock_thread)
    return msg


def _make_bot() -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.user = MagicMock()
    return bot


def _make_cog(bot: MagicMock | None = None) -> JobFailureTriageCog:
    if bot is None:
        bot = _make_bot()
    runner = MagicMock()
    runner.clone = MagicMock(return_value=MagicMock())
    components = MagicMock()
    return JobFailureTriageCog(bot, runner, components)


# ---------------------------------------------------------------------------
# _extract_failure_info tests
# ---------------------------------------------------------------------------


class TestExtractFailureInfo:
    def test_extracts_job_failed_embed(self) -> None:
        embed = _make_failure_embed()
        info = _extract_failure_info(embed)
        assert info is not None
        assert info["title"] == "Job Failed"
        assert info["job_id"] == "bluesky_youtube_post"
        assert info["job_name"] == "bluesky_youtube_post"
        assert "429" in info["error"]
        assert info["schedule"] == "daily_post"

    def test_extracts_job_timeout_embed(self) -> None:
        embed = _make_timeout_embed()
        info = _extract_failure_info(embed)
        assert info is not None
        assert info["title"] == "Job Timeout"
        assert info["job_id"] == "ai_full_maintenance"

    def test_ignores_success_embed(self) -> None:
        embed = _make_success_embed()
        info = _extract_failure_info(embed)
        assert info is None

    def test_ignores_embed_without_title(self) -> None:
        embed = discord.Embed(description="no title")
        info = _extract_failure_info(embed)
        assert info is None

    def test_extracts_job_name_from_description(self) -> None:
        embed = _make_failure_embed(description="**my_custom_job** が失敗しました")
        info = _extract_failure_info(embed)
        assert info is not None
        assert info["job_name"] == "my_custom_job"

    def test_falls_back_to_job_id_when_no_bold_in_description(self) -> None:
        embed = _make_failure_embed(description="Something went wrong")
        info = _extract_failure_info(embed)
        assert info is not None
        assert info["job_name"] == info["job_id"]


# ---------------------------------------------------------------------------
# on_message — skip conditions
# ---------------------------------------------------------------------------


class TestOnMessageSkip:
    @pytest.mark.asyncio
    async def test_ignores_bot_own_message(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()])
        msg.author = cog.bot.user

        with patch.object(cog, "_start_triage") as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_wrong_channel(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()], channel_id=999999)

        with patch.object(cog, "_start_triage") as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_message_without_embeds(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[])

        with patch.object(cog, "_start_triage") as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_success_embed(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_success_embed()])

        with patch.object(cog, "_start_triage") as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_duplicate_message(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()])
        cog._triaging.add(msg.id)

        with patch.object(cog, "_start_triage") as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_webhook_message(self) -> None:
        """Non-webhook messages (e.g. regular user messages) are ignored."""
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()], webhook_id=None)

        with patch.object(cog, "_start_triage") as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_not_called()


# ---------------------------------------------------------------------------
# on_message — detection
# ---------------------------------------------------------------------------


class TestOnMessageDetect:
    @pytest.mark.asyncio
    async def test_triggers_triage_for_failure(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()])

        with patch.object(cog, "_start_triage", new_callable=AsyncMock) as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_triggers_triage_for_timeout(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_timeout_embed()])

        with patch.object(cog, "_start_triage", new_callable=AsyncMock) as mock_triage:
            await cog.on_message(msg)

        mock_triage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_removes_from_triaging_after_completion(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()])

        with patch.object(cog, "_start_triage", new_callable=AsyncMock):
            await cog.on_message(msg)

        assert msg.id not in cog._triaging

    @pytest.mark.asyncio
    async def test_removes_from_triaging_on_error(self) -> None:
        cog = _make_cog()
        msg = _make_message(embeds=[_make_failure_embed()])

        with patch.object(
            cog, "_start_triage", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            await cog.on_message(msg)

        assert msg.id not in cog._triaging


# ---------------------------------------------------------------------------
# _start_triage — thread creation and Claude invocation
# ---------------------------------------------------------------------------


class TestStartTriage:
    @pytest.mark.asyncio
    async def test_creates_thread_on_failure_message(self) -> None:
        cog = _make_cog()
        embed = _make_failure_embed()
        msg = _make_message(embeds=[embed])

        with patch(
            "examples.ebibot.cogs.job_failure_triage.run_claude_with_config",
            new_callable=AsyncMock,
        ):
            await cog._start_triage(msg, _extract_failure_info(embed))

        msg.create_thread.assert_awaited_once()
        # Thread name should contain the job name
        call_kwargs = msg.create_thread.call_args
        assert "bluesky_youtube_post" in call_kwargs.kwargs.get(
            "name", call_kwargs.args[0] if call_kwargs.args else ""
        )

    @pytest.mark.asyncio
    async def test_skips_when_runner_is_none(self) -> None:
        cog = _make_cog()
        cog.runner = None
        embed = _make_failure_embed()
        msg = _make_message(embeds=[embed])

        with patch(
            "examples.ebibot.cogs.job_failure_triage.run_claude_with_config",
            new_callable=AsyncMock,
        ) as mock_run:
            await cog._start_triage(msg, _extract_failure_info(embed))

        mock_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prompt_includes_job_details(self) -> None:
        cog = _make_cog()
        embed = _make_failure_embed(
            job_id="bluesky_youtube_post",
            error="```\nHTTP 429: rate limit\n```",
        )
        msg = _make_message(embeds=[embed])

        captured_config = None

        async def capture(config):  # type: ignore[no-untyped-def]
            nonlocal captured_config
            captured_config = config

        with patch(
            "examples.ebibot.cogs.job_failure_triage.run_claude_with_config",
            side_effect=capture,
        ):
            await cog._start_triage(msg, _extract_failure_info(embed))

        assert captured_config is not None
        assert "bluesky_youtube_post" in captured_config.prompt
        assert "429" in captured_config.prompt

    @pytest.mark.asyncio
    async def test_skips_non_text_channel(self) -> None:
        cog = _make_cog()
        embed = _make_failure_embed()
        msg = _make_message(embeds=[embed])
        msg.channel = MagicMock(spec=discord.DMChannel)  # Not a TextChannel

        with patch(
            "examples.ebibot.cogs.job_failure_triage.run_claude_with_config",
            new_callable=AsyncMock,
        ) as mock_run:
            await cog._start_triage(msg, _extract_failure_info(embed))

        mock_run.assert_not_awaited()
