"""廃盤管理コマンド Cog — /haiban で廃盤登録・原価変更・一覧表示.

使い方:
  /haiban action:廃盤登録 jan:4971618011312 note:メーカー終売
  /haiban action:原価変更 jan:4971618011312 old_price:850 new_price:780 reason:廃盤処分
  /haiban action:一覧
  /haiban action:レポート
  /haiban action:在庫チェック
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SCRIPT = "/home/ubuntu/ec-automation-system/scripts/haiban_manager.py"
SCRIPT_CWD = "/home/ubuntu/ec-automation-system"
ENV_FILE = "/home/ubuntu/ec-automation-system/scripts/.env"
TIMEOUT = 120

COLOR_WORKING = 0xF39C12
COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR = 0xE74C3C
COLOR_WARNING = 0xFF4444


def _build_subprocess_env() -> dict[str, str]:
    """サブプロセス用の環境変数を構築."""
    env = {**os.environ}
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        logger.warning("env file not found: %s", ENV_FILE)
    return env


class HaibanCommandCog(commands.Cog):
    """廃盤管理コマンド — SS-01の廃盤ステータス管理・原価変更履歴."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="haiban",
        description="廃盤管理（廃盤登録・原価変更・一覧・レポート・在庫チェック）",
    )
    @app_commands.describe(
        action="実行するアクション",
        jan="JANコード（13桁）",
        status="廃盤ステータス（廃盤登録時）",
        note="備考・理由",
        old_price="旧原価（税抜、原価変更時）",
        new_price="新原価（税抜、原価変更時）",
        condition="条件区分（原価変更時）",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="廃盤登録", value="discontinue"),
            app_commands.Choice(name="原価変更", value="price-change"),
            app_commands.Choice(name="一覧", value="list"),
            app_commands.Choice(name="レポート", value="report"),
            app_commands.Choice(name="在庫チェック", value="check-stock"),
        ],
        status=[
            app_commands.Choice(name="廃盤(在庫限り)", value="廃盤(在庫限り)"),
            app_commands.Choice(name="廃盤(完売)", value="廃盤(完売)"),
            app_commands.Choice(name="一時停止", value="一時停止"),
        ],
        condition=[
            app_commands.Choice(name="通常変更", value="通常変更"),
            app_commands.Choice(name="期間限定", value="期間限定"),
            app_commands.Choice(name="最終仕入", value="最終仕入"),
        ],
    )
    async def haiban(
        self,
        interaction: discord.Interaction,
        action: str,
        jan: str = "",
        status: str = "廃盤(在庫限り)",
        note: str = "",
        old_price: float = 0.0,
        new_price: float = 0.0,
        condition: str = "通常変更",
    ) -> None:
        """廃盤管理コマンド."""
        # コマンド組み立て
        cmd = ["python3", SCRIPT]

        if action == "discontinue":
            if not jan:
                await interaction.response.send_message(
                    "JANコードを指定してください。", ephemeral=True
                )
                return
            cmd.extend(["discontinue", "--jan", jan, "--status", status])
            if note:
                cmd.extend(["--note", note])
            title = f"廃盤登録中... JAN: {jan}"

        elif action == "price-change":
            if not jan or not old_price or not new_price:
                await interaction.response.send_message(
                    "JANコード・旧原価・新原価を指定してください。", ephemeral=True
                )
                return
            cmd.extend([
                "price-change",
                "--jan", jan,
                "--old-price", str(old_price),
                "--new-price", str(new_price),
                "--condition", condition,
            ])
            if note:
                cmd.extend(["--reason", note])
            title = f"原価変更中... JAN: {jan}"

        elif action == "list":
            cmd.append("list")
            title = "廃盤商品一覧を取得中..."

        elif action == "report":
            cmd.append("report")
            title = "棚卸用原価レポートを取得中..."

        elif action == "check-stock":
            cmd.append("check-stock")
            title = "廃盤在庫チェック中..."

        else:
            await interaction.response.send_message(
                "不明なアクションです。", ephemeral=True
            )
            return

        # 進捗表示
        embed = discord.Embed(title=title, color=COLOR_WORKING)
        await interaction.response.send_message(embed=embed)

        # 実行
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=SCRIPT_CWD,
                env=_build_subprocess_env(),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="タイムアウト",
                description="処理に時間がかかりすぎました。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("haiban command failed")
            embed = discord.Embed(
                title="エラー",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        if proc.returncode == 0:
            # 結果表示
            result_text = stdout_text.strip()
            if len(result_text) > 1800:
                result_text = result_text[:1800] + "\n..."

            if action == "discontinue":
                embed_title = f"廃盤登録完了: JAN {jan}"
                color = COLOR_WARNING
            elif action == "price-change":
                embed_title = f"原価変更完了: JAN {jan}"
                color = COLOR_SUCCESS
            elif action == "check-stock":
                embed_title = "廃盤在庫チェック完了"
                color = COLOR_SUCCESS
            else:
                embed_title = "完了"
                color = COLOR_SUCCESS

            embed = discord.Embed(title=embed_title, color=color)
            if result_text:
                embed.add_field(
                    name="結果",
                    value=f"```\n{result_text[:1000]}\n```",
                    inline=False,
                )
        else:
            err = stderr_text[:800] if stderr_text else stdout_text[:800] or "不明なエラー"
            embed = discord.Embed(
                title="エラー",
                description=f"```\n{err}\n```",
                color=COLOR_ERROR,
            )

        await interaction.edit_original_response(embed=embed)

        logger.info(
            "/haiban by %s: action=%s, jan=%s, rc=%s",
            interaction.user.name, action, jan, proc.returncode,
        )
