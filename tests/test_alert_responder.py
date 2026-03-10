"""tests/test_alert_responder.py

AlertResponderCog のユニットテスト。
Discord オブジェクトと Claude ランナーをモックして、
アラート検知・スキップ・スレッド作成・重複防止の各経路を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from examples.ebibot.cogs.alert_responder import _ALERT_PATTERN, ALERT_CHANNEL_ID, AlertResponderCog

# ---------------------------------------------------------------------------
# パターン検証（⚠️ マッチング）
# ---------------------------------------------------------------------------


class TestAlertPattern:
    def test_warning_emoji_matches(self) -> None:
        assert _ALERT_PATTERN.search("[BlueSky] ⚠️ ch5: Gemini が使えなかった")

    def test_plain_message_does_not_match(self) -> None:
        assert not _ALERT_PATTERN.search("[BlueSky] ✅ 投稿完了")

    def test_error_without_warning_emoji_does_not_match(self) -> None:
        assert not _ALERT_PATTERN.search("[Agent Pipeline] エラー: 詳細ログ参照")


# ---------------------------------------------------------------------------
# ヘルパー — Discord モックオブジェクト生成
# ---------------------------------------------------------------------------


def _make_text_channel(channel_id: int) -> MagicMock:
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    ch.create_thread = AsyncMock()
    return ch


def _make_message(
    content: str,
    channel_id: int = ALERT_CHANNEL_ID,
    is_bot: bool = False,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.id = 12345
    msg.author = MagicMock()
    msg.author.bot = is_bot
    channel = _make_text_channel(channel_id)
    msg.channel = channel
    # create_thread はメッセージ自体にも必要（スレッド作成時）
    mock_thread = AsyncMock(spec=discord.Thread)
    mock_thread.id = 99999
    mock_thread.send = AsyncMock()
    msg.create_thread = AsyncMock(return_value=mock_thread)
    return msg


def _make_bot(is_bot_author: bool = False) -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.user = MagicMock()
    bot.user.bot = is_bot_author
    return bot


def _make_cog(bot: MagicMock | None = None) -> AlertResponderCog:
    if bot is None:
        bot = _make_bot()
    runner = MagicMock()
    runner.clone = MagicMock(return_value=MagicMock())
    components = MagicMock()
    cog = AlertResponderCog(bot, runner, components)
    # bot.user を自分自身として設定（Bot 自身の発言をスキップするため）
    bot_user = MagicMock()
    cog.bot.user = bot_user
    return cog


# ---------------------------------------------------------------------------
# on_message — スキップ条件
# ---------------------------------------------------------------------------


class TestOnMessageSkip:
    @pytest.mark.asyncio
    async def test_ignores_bot_own_message(self) -> None:
        """Bot 自身のメッセージは無視する"""
        cog = _make_cog()
        msg = _make_message("⚠️ テスト")
        msg.author = cog.bot.user  # Bot 自身

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_wrong_channel(self) -> None:
        """監視チャンネル以外のメッセージは無視する"""
        cog = _make_cog()
        msg = _make_message("⚠️ テスト", channel_id=999999)  # 別チャンネル

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_alert_message(self) -> None:
        """⚠️ を含まないメッセージは無視する"""
        cog = _make_cog()
        msg = _make_message("✅ 投稿完了: https://bsky.app/...")

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_duplicate_message(self) -> None:
        """同じメッセージへの二重調査を防ぐ"""
        cog = _make_cog()
        msg = _make_message("⚠️ テスト")
        cog._investigating.add(msg.id)  # 調査中フラグを立てる

        with patch.object(cog, "_start_investigation") as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_not_called()


# ---------------------------------------------------------------------------
# on_message — 検知条件
# ---------------------------------------------------------------------------


class TestOnMessageDetect:
    @pytest.mark.asyncio
    async def test_triggers_investigation_for_alert(self) -> None:
        """⚠️ を含むメッセージで調査を開始する"""
        cog = _make_cog()
        msg = _make_message("[BlueSky] ⚠️ ch5: Gemini が使えなかった")

        with patch.object(cog, "_start_investigation", new_callable=AsyncMock) as mock_inv:
            await cog.on_message(msg)

        mock_inv.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_removes_message_from_investigating_after_completion(self) -> None:
        """調査完了後、_investigating からメッセージ ID が除去される"""
        cog = _make_cog()
        msg = _make_message("⚠️ テスト")

        with patch.object(cog, "_start_investigation", new_callable=AsyncMock):
            await cog.on_message(msg)

        assert msg.id not in cog._investigating

    @pytest.mark.asyncio
    async def test_removes_message_from_investigating_on_error(self) -> None:
        """調査中に例外が発生しても _investigating からクリーンアップされる"""
        cog = _make_cog()
        msg = _make_message("⚠️ テスト")

        with patch.object(
            cog,
            "_start_investigation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("test error"),
        ):
            await cog.on_message(msg)  # 例外を飲み込むことを確認

        assert msg.id not in cog._investigating


# ---------------------------------------------------------------------------
# _start_investigation — スレッド作成
# ---------------------------------------------------------------------------


class TestStartInvestigation:
    @pytest.mark.asyncio
    async def test_creates_thread_on_alert_message(self) -> None:
        """アラートメッセージにスレッドを作成する"""
        cog = _make_cog()
        msg = _make_message("[BlueSky] ⚠️ ch5: Gemini タイムアウト")

        with patch(
            "examples.ebibot.cogs.alert_responder.run_claude_with_config", new_callable=AsyncMock
        ):
            await cog._start_investigation(msg)

        msg.create_thread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_runner_is_none(self) -> None:
        """runner が None の場合はスレッドを作らない"""
        cog = _make_cog()
        cog.runner = None
        msg = _make_message("⚠️ テスト")

        with patch(
            "examples.ebibot.cogs.alert_responder.run_claude_with_config", new_callable=AsyncMock
        ) as mock_run:
            await cog._start_investigation(msg)

        mock_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_alert_text_included_in_prompt(self) -> None:
        """アラート文がプロンプトに含まれる"""
        cog = _make_cog()
        alert_text = "[BlueSky] ⚠️ ch5: Gemini が使えなかったため"
        msg = _make_message(alert_text)

        captured_config = None

        async def capture(config):
            nonlocal captured_config
            captured_config = config

        with patch(
            "examples.ebibot.cogs.alert_responder.run_claude_with_config", side_effect=capture
        ):
            await cog._start_investigation(msg)

        assert captured_config is not None
        assert alert_text in captured_config.prompt
