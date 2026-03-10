"""alert_responder.py — 警告・エラーアラートの自動調査 Cog

特定の Discord チャンネルに投稿された警告メッセージを検知し、
Claude Code を自動起動して根本原因を調査・PR作成・Discord報告まで行う。

設定:
    ALERT_MONITOR_CHANNEL_ID  監視するチャンネル ID（デフォルト: 1475628079945879757）
    DISCORD_OWNER_ID          メンション対象のオーナーユーザー ID（省略可）

アラートの判定条件:
    - 監視チャンネル内のメッセージであること
    - Bot 自身の発言でないこと
    - メッセージに「⚠️」が含まれること
"""

from __future__ import annotations

import logging
import os
import re

import discord
from discord.ext import commands

from claude_discord.cogs._run_helper import run_claude_with_config
from claude_discord.cogs.run_config import RunConfig

logger = logging.getLogger(__name__)

# 監視チャンネル ID（環境変数で上書き可）
_DEFAULT_ALERT_CHANNEL_ID = 1475628079945879757
ALERT_CHANNEL_ID = int(os.environ.get("ALERT_MONITOR_CHANNEL_ID", _DEFAULT_ALERT_CHANNEL_ID))

# ⚠️ を含むメッセージをアラートと見なす
_ALERT_PATTERN = re.compile(r"⚠️")

# 調査用 Claude Code プロンプトテンプレート
_INVESTIGATION_PROMPT = """\
以下の自動アラートが届きました。根本原因を調査して修正 PR を作成してください。

## アラート内容

```
{alert_text}
```

## 作業手順

1. アラートの内容からリポジトリ・スクリプト・ログファイルを特定する
2. 関連するコード・最新ログを読んで根本原因を特定する
3. 修正を実装し、テストを追加する（TDD 採用プロジェクトの場合はテストを先に書く）
4. CI/テストが通ることを確認する
5. GitHub に PR を作成する
   - privateリポジトリなら日本語でOK
   - publicリポジトリなら英語で
6. このスレッドに以下を報告する:
   - 根本原因（1〜2行で要約）
   - 実施した修正の概要
   - PR URL

## 注意

- worktree を使って作業すること（他セッションへの影響を防ぐため）
- テストが通らない場合は PR を作らず、その旨を報告すること
- 判断に迷う変更（設計変更・破壊的変更）は実装せず報告だけすること
"""


class AlertResponderCog(commands.Cog):
    """監視チャンネルの警告を自動調査する Cog。"""

    def __init__(self, bot: commands.Bot, runner: object, components: object) -> None:
        self.bot = bot
        self.runner = runner
        self.components = components
        # 同一メッセージへの二重調査を防ぐ
        self._investigating: set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """監視チャンネルに届いたメッセージをチェックし、アラートなら調査を開始する。"""
        # Bot 自身の発言は無視
        if message.author == self.bot.user:
            return

        # 監視チャンネル以外は無視
        if message.channel.id != ALERT_CHANNEL_ID:
            return

        # ⚠️ を含まないメッセージは無視
        if not _ALERT_PATTERN.search(message.content):
            return

        # 既に調査中の場合はスキップ
        if message.id in self._investigating:
            return

        self._investigating.add(message.id)
        try:
            await self._start_investigation(message)
        except Exception:
            logger.exception(
                "AlertResponderCog: 調査開始中に予期しないエラー (message_id=%d)", message.id
            )
        finally:
            self._investigating.discard(message.id)

    async def _start_investigation(self, alert_message: discord.Message) -> None:
        """スレッドを作成し、Claude Code で調査を実行する。"""
        if not isinstance(alert_message.channel, discord.TextChannel):
            logger.warning("AlertResponderCog: チャンネルが TextChannel でない — スキップ")
            return

        if self.runner is None:
            logger.warning("AlertResponderCog: runner が None — Claude 起動不可")
            return

        logger.info(
            "AlertResponderCog: アラート検知 (channel=%d, message=%d) — 調査開始",
            alert_message.channel.id,
            alert_message.id,
        )

        # アラートメッセージにスレッドを作成
        thread = await alert_message.create_thread(
            name=f"🔍 自動調査: {alert_message.content[:50]}",
            auto_archive_duration=1440,  # 24時間
        )

        owner_id = os.environ.get("DISCORD_OWNER_ID", "")
        mention = f"<@{owner_id}> " if owner_id else ""
        await thread.send(
            f"{mention}🔍 アラートを検知しました。Claude Code が根本原因を調査します..."
        )

        prompt = _INVESTIGATION_PROMPT.format(alert_text=alert_message.content)

        session_repo = getattr(self.components, "session_repo", None)
        registry = getattr(self.bot, "session_registry", None)
        lounge_repo = getattr(self.components, "lounge_repo", None)

        cloned_runner = self.runner.clone()

        await run_claude_with_config(
            RunConfig(
                thread=thread,
                runner=cloned_runner,
                prompt=prompt,
                session_id=None,
                repo=session_repo,
                registry=registry,
                lounge_repo=lounge_repo,
            )
        )


async def setup(bot: commands.Bot, runner: object, components: object) -> None:
    """カスタム Cog ローダーから呼ばれるエントリポイント。"""
    await bot.add_cog(AlertResponderCog(bot, runner, components))
    logger.info(
        "AlertResponderCog loaded — monitoring channel %d for ⚠️ alerts",
        ALERT_CHANNEL_ID,
    )
