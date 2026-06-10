"""商品書き出しコマンド Cog — /pro-kakidasi でGoQ在庫連携シート生成.

JANを起点に各モールAPIから商品データを取得し、SS-08のシート5〜11に書き込む。
JAN複数指定はカンマ・スペース・読点区切り対応。

使い方:
  /pro-kakidasi action:fetch                                      → 全モール取得（SS-17由来）
  /pro-kakidasi action:fetch mall:amazon1                         → 特定モールのみ
  /pro-kakidasi action:write jan:4972228224055                    → 単一JANで追記
  /pro-kakidasi action:write jan:4972228224055,4972228263122      → 複数JAN追記
  /pro-kakidasi action:write jan:"4972228224055 4972228263122"    → スペース区切りも可
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SCRIPT = "/home/ubuntu/ec-automation-system/scripts/goq_inventory_sync.py"
SCRIPT_CWD = "/home/ubuntu/ec-automation-system"
ENV_FILE = "/home/ubuntu/ec-automation-system/scripts/.env"
SP_API_CREDENTIALS = "/home/ubuntu/.config/sp-api-credentials.json"
TIMEOUT = 600


def _build_subprocess_env() -> dict[str, str]:
    """サブプロセス用の環境変数を構築（SP-API / auPAY / Qoo10 / Yahoo 認証情報を確実に渡す）.

    Bot のHOMEがどこにあっても、ec-automation-system/scripts/.env と
    SP-API credentials JSON が読めるよう絶対パスを明示。これで Amazon が
    認証エラーで取れないケースを防ぐ。
    """
    env = {**os.environ}
    env.setdefault("SP_API_CREDENTIALS", SP_API_CREDENTIALS)
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

COLOR_WORKING = 0xF39C12
COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR = 0xE74C3C

MALL_CHOICES = [
    app_commands.Choice(name="全モール", value="all"),
    app_commands.Choice(name="Amazon1", value="amazon1"),
    app_commands.Choice(name="Amazon2", value="amazon2"),
    app_commands.Choice(name="Yahoo", value="yahoo"),
    app_commands.Choice(name="auPAY", value="aupay"),
    app_commands.Choice(name="Qoo10(1)", value="qoo10_1"),
    app_commands.Choice(name="Qoo10(2)", value="qoo10_2"),
    app_commands.Choice(name="Temu", value="temu"),
]


class ZaikoCommandCog(commands.Cog):
    """在庫連携コマンド — SS-08にモールAPIデータを書き込み."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="pro-kakidasi",
        description="GoQ在庫連携シート生成（SS-08シート5〜11）",
    )
    @app_commands.describe(
        action="fetch=取得のみ表示 / write=SS-08に書き込み",
        mall="対象モール（未指定=全モール）",
        jan="JANコード（複数はカンマ/スペース区切り。例: 4972228224055,4972228263122）",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="fetch（取得のみ）", value="fetch"),
            app_commands.Choice(name="write（SS-08書き込み）", value="write"),
        ],
        mall=MALL_CHOICES,
    )
    async def pro_kakidasi(
        self,
        interaction: discord.Interaction,
        action: str = "fetch",
        mall: str = "all",
        jan: str = "",
    ) -> None:
        """GoQ在庫連携シート生成."""
        # JANパース（カンマ・スペース・読点区切り対応、複数JAN対応）
        jan_list: list[str] = []
        if jan.strip():
            raw = jan.replace(",", " ").replace("、", " ").replace("\n", " ")
            for j in raw.split():
                j = j.strip()
                if not j:
                    continue
                if not j.isdigit() or len(j) not in (8, 13):
                    await interaction.response.send_message(
                        f"JAN `{j}` が不正です。8桁または13桁の数字で入力してください。",
                        ephemeral=True,
                    )
                    return
                jan_list.append(j)

        # コマンド組み立て
        cmd = ["python3", SCRIPT, action]
        if mall != "all":
            cmd.extend(["--mall", mall])
        if jan_list:
            cmd.append("--jan")
            cmd.extend(jan_list)

        # 進捗表示
        mall_label = mall if mall != "all" else "全モール"
        if jan_list:
            jan_label = f"JAN ({len(jan_list)}件): `{', '.join(jan_list)}`"
        else:
            jan_label = "SS-17由来 全商品"
        embed = discord.Embed(
            title=f"在庫連携 {action} 実行中...",
            description=f"モール: **{mall_label}** / {jan_label}",
            color=COLOR_WORKING,
        )
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
            logger.exception("zaiko command failed")
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
            # サマリ部分を抽出
            lines = stdout_text.strip().split("\n")
            summary_lines = []
            in_summary = False
            for ln in lines:
                if "サマリ" in ln:
                    in_summary = True
                    continue
                if in_summary and ln.strip():
                    summary_lines.append(ln.strip())
                if "完了" in ln:
                    summary_lines.append(ln.strip())

            if not summary_lines:
                summary_lines = [ln.strip() for ln in lines[-10:] if ln.strip()]

            result_text = "\n".join(summary_lines[-15:])

            embed = discord.Embed(
                title=f"在庫連携 {action} 完了",
                description=f"モール: **{mall_label}** / {jan_label}",
                color=COLOR_SUCCESS,
            )
            if result_text:
                embed.add_field(
                    name="結果",
                    value=f"```\n{result_text[:1000]}\n```",
                    inline=False,
                )
        else:
            err = stderr_text[:800] if stderr_text else stdout_text[:800] or "不明なエラー"
            embed = discord.Embed(
                title="在庫連携エラー",
                description=f"```\n{err}\n```",
                color=COLOR_ERROR,
            )

        await interaction.edit_original_response(embed=embed)

        logger.info(
            "/pro-kakidasi by %s: action=%s, mall=%s, jan_count=%d, rc=%s",
            interaction.user.name, action, mall, len(jan_list), proc.returncode,
        )
