"""Tests for the /search slash command (SessionManageCog)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from claude_discord.cogs.session_manage import SessionManageCog, build_search_embed
from claude_discord.database.repository import SessionRecord


def _record(thread_id: int, summary: str, *, origin: str = "discord") -> SessionRecord:
    return SessionRecord(
        thread_id=thread_id,
        session_id=f"sess-{thread_id}",
        working_dir="/home/ebi",
        model=None,
        origin=origin,
        summary=summary,
        created_at="2026-07-22 10:00:00",
        last_used_at="2026-07-23 09:00:00",
    )


def test_build_search_embed_includes_deep_link() -> None:
    embed = build_search_embed(
        "substack",
        [_record(1001, "Fix Substack sync failure")],
        guild_id=111,
    )
    body = "\n".join(f.value for f in embed.fields)
    assert "https://discord.com/channels/111/1001" in body


def test_build_search_embed_no_results() -> None:
    embed = build_search_embed("zzz", [], guild_id=111)
    assert embed.description is not None
    assert "No" in embed.description or "見つかりません" in embed.description


def test_build_search_embed_without_guild_omits_link() -> None:
    embed = build_search_embed("x", [_record(1, "something")], guild_id=None)
    body = "\n".join(f.value for f in embed.fields)
    assert "discord.com/channels" not in body


def _make_cog() -> SessionManageCog:
    bot = MagicMock()
    repo = MagicMock()
    repo.search = AsyncMock(return_value=[_record(1001, "Fix Substack sync failure")])
    return SessionManageCog(bot=bot, repo=repo)


async def test_search_command_queries_repo_and_replies() -> None:
    cog = _make_cog()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 111
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.search_command.callback(cog, interaction, query="substack", origin=None)

    cog.repo.search.assert_awaited_once()
    assert cog.repo.search.await_args.kwargs["query"] == "substack"
    interaction.response.send_message.assert_awaited_once()


async def test_search_command_rejects_blank_query() -> None:
    cog = _make_cog()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 111
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.search_command.callback(cog, interaction, query="   ", origin=None)

    cog.repo.search.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
