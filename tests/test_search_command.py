"""Tests for the /search slash command (SessionManageCog)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from claude_code_core.thread_search import ThreadSearchResult
from claude_discord.cogs.session_manage import SessionManageCog, build_search_embed


def _result(
    thread_id: int | None,
    summary: str | None,
    *,
    origin: str = "discord",
    source: str = "summary",
    snippet: str | None = None,
    session_id: str | None = None,
) -> ThreadSearchResult:
    return ThreadSearchResult(
        thread_id=thread_id,
        session_id=session_id or (f"sess-{thread_id}" if thread_id else "sess-x"),
        summary=summary,
        working_dir="/home/ebi",
        origin=origin,
        last_used_at="2026-07-23 09:00:00",
        snippet=snippet,
        source=source,
    )


def test_build_search_embed_includes_deep_link() -> None:
    embed = build_search_embed(
        "substack",
        [_result(1001, "Fix Substack sync failure")],
        guild_id=111,
    )
    body = "\n".join(f.value for f in embed.fields)
    assert "https://discord.com/channels/111/1001" in body


def test_build_search_embed_no_results() -> None:
    embed = build_search_embed("zzz", [], guild_id=111)
    assert embed.description is not None
    assert "No" in embed.description


def test_build_search_embed_without_guild_omits_link() -> None:
    embed = build_search_embed("x", [_result(1, "something")], guild_id=None)
    body = "\n".join(f.value for f in embed.fields)
    assert "discord.com/channels" not in body


def test_build_search_embed_body_hit_shows_snippet() -> None:
    embed = build_search_embed(
        "dns",
        [_result(5, "opening prompt", source="body", snippet="we changed the DNS records")],
        guild_id=111,
    )
    body = "\n".join(f.value for f in embed.fields)
    assert "we changed the DNS records" in body


def test_build_search_embed_orphan_shows_resume_hint() -> None:
    embed = build_search_embed(
        "kube",
        [_result(None, None, source="body", snippet="mentions kubernetes", session_id="uuid-123")],
        guild_id=111,
    )
    body = "\n".join(f.value for f in embed.fields)
    assert "claude --resume uuid-123" in body
    assert "discord.com/channels" not in body


def _make_cog() -> SessionManageCog:
    bot = MagicMock()
    repo = MagicMock()
    repo.search = AsyncMock(return_value=[])
    repo.get_by_session_id = AsyncMock(return_value=None)
    return SessionManageCog(bot=bot, repo=repo)


async def test_search_command_summary_path_uses_send_message() -> None:
    cog = _make_cog()
    cog.repo.search = AsyncMock(
        return_value=[
            MagicMock(
                thread_id=1001,
                session_id="s",
                summary="Fix Substack sync",
                working_dir="/home/ebi",
                origin="discord",
                last_used_at="2026-07-23 09:00:00",
            )
        ]
    )
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 111
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.search_command.callback(cog, interaction, query="substack", origin=None, body=False)

    cog.repo.search.assert_awaited_once()
    interaction.response.send_message.assert_awaited_once()


async def test_search_command_body_path_defers_and_followups() -> None:
    cog = _make_cog()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 111
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.search_command.callback(cog, interaction, query="substack", origin=None, body=True)

    interaction.response.defer.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()


async def test_search_command_rejects_blank_query() -> None:
    cog = _make_cog()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 111
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.search_command.callback(cog, interaction, query="   ", origin=None, body=False)

    cog.repo.search.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
