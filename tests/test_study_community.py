"""Tests for the opt-in, read-only study community assistant Cog."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from examples.ebibot.cogs.study_community import (
    EXAM_CONTENT_REFUSAL,
    StudyAssistantConfig,
    StudyCommunityCog,
    chunk_discord_message,
    looks_like_recalled_exam_content,
)

FORUM_ID = 123456789012345678
MEMBER_ROLE_ID = 223456789012345678


def _config(**overrides: object) -> StudyAssistantConfig:
    values: dict[str, object] = {
        "forum_id": FORUM_ID,
        "member_role_id": MEMBER_ROLE_ID,
        "api_key": "test-key",
        "model": "gpt-5-mini",
        "cooldown_seconds": 30.0,
        "max_input_chars": 4_000,
        "max_output_tokens": 1_200,
        "max_concurrency": 2,
    }
    values.update(overrides)
    return StudyAssistantConfig(**values)  # type: ignore[arg-type]


def _message(
    content: str = "可用性ゾーンとは何ですか？",
    *,
    parent_id: int = FORUM_ID,
    author_id: int = 42,
    bot: bool = False,
    role_ids: tuple[int, ...] = (MEMBER_ROLE_ID,),
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.content = content
    message.id = 777
    message.author = MagicMock(spec=discord.Member)
    message.author.id = author_id
    message.author.bot = bot
    message.author.roles = [MagicMock(id=role_id) for role_id in role_ids]
    message.channel = MagicMock(spec=discord.Thread)
    message.channel.parent_id = parent_id
    message.channel.send = AsyncMock()
    typing = MagicMock()
    typing.__aenter__ = AsyncMock(return_value=None)
    typing.__aexit__ = AsyncMock(return_value=None)
    message.channel.typing.return_value = typing
    return message


def _cog(config: StudyAssistantConfig | None = None) -> tuple[StudyCommunityCog, AsyncMock]:
    client = AsyncMock()
    client.answer.return_value = "可用性ゾーンは、リージョン内の独立した拠点です。"
    bot = MagicMock(spec=commands.Bot)
    cog = StudyCommunityCog(bot, config or _config(), client=client)
    return cog, client


class TestExamContentGuard:
    @pytest.mark.parametrize(
        "text",
        [
            "今日の試験で実際に出た問題と正解を教えます",
            "本番で出た選択肢はAとBでした。どちらが正解？",
            "AZ-900のexam dumpを解説して",
        ],
    )
    def test_detects_recalled_or_dumped_exam_content(self, text: str) -> None:
        assert looks_like_recalled_exam_content(text)

    def test_allows_conceptual_study_question(self) -> None:
        assert not looks_like_recalled_exam_content("可用性ゾーンと可用性セットの違いは？")


class TestChunking:
    def test_chunks_under_discord_limit_without_losing_text(self) -> None:
        text = ("abcde\n" * 800).strip()
        chunks = chunk_discord_message(text, limit=1_900)
        assert chunks
        assert all(len(chunk) <= 1_900 for chunk in chunks)
        assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


class TestRouting:
    @pytest.mark.asyncio
    async def test_ignores_bot_messages(self) -> None:
        cog, client = _cog()
        message = _message(bot=True)
        await cog.on_message(message)
        client.answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ignores_threads_outside_configured_forum(self) -> None:
        cog, client = _cog()
        message = _message(parent_id=999)
        await cog.on_message(message)
        client.answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ignores_users_without_configured_role(self) -> None:
        cog, client = _cog()
        message = _message(role_ids=())
        await cog.on_message(message)
        client.answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_answers_member_question_in_configured_forum(self) -> None:
        cog, client = _cog()
        message = _message()
        await cog.on_message(message)
        client.answer.assert_awaited_once_with("可用性ゾーンとは何ですか？")
        message.channel.send.assert_awaited_once()
        mentions = message.channel.send.await_args.kwargs["allowed_mentions"]
        assert mentions.everyone is False
        assert mentions.users is False
        assert mentions.roles is False


class TestSafetyAndLimits:
    @pytest.mark.asyncio
    async def test_refuses_recalled_exam_content_without_api_call(self) -> None:
        cog, client = _cog()
        message = _message("昨日の本番試験で実際に出た問題の正解を教えて")
        await cog.on_message(message)
        client.answer.assert_not_awaited()
        message.channel.send.assert_awaited_once()
        assert message.channel.send.await_args.args == (EXAM_CONTENT_REFUSAL,)
        mentions = message.channel.send.await_args.kwargs["allowed_mentions"]
        assert mentions.everyone is False
        assert mentions.users is False
        assert mentions.roles is False

    @pytest.mark.asyncio
    async def test_enforces_per_user_cooldown(self) -> None:
        cog, client = _cog(_config(cooldown_seconds=3600.0))
        first = _message(author_id=42)
        second = _message("次の質問", author_id=42)
        await cog.on_message(first)
        await cog.on_message(second)
        client.answer.assert_awaited_once()
        assert "少し待って" in second.channel.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_truncates_question_before_api_call(self) -> None:
        cog, client = _cog(_config(max_input_chars=20))
        message = _message("あ" * 100)
        await cog.on_message(message)
        assert len(client.answer.await_args.args[0]) == 20

    @pytest.mark.asyncio
    async def test_hides_provider_error_details(self) -> None:
        cog, client = _cog()
        client.answer.side_effect = RuntimeError("secret provider details")
        message = _message()
        await cog.on_message(message)
        sent = message.channel.send.await_args.args[0]
        assert "時間をおいて" in sent
        assert "secret" not in sent
