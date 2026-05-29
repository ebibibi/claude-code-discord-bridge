"""カテゴリ検索コマンド Cog — /category-search で全7モールカテゴリ一括検索.

商品名やキーワードから全モールのカテゴリIDを検索。
CSVマスタベース（JAN→API正引きが優先）。

使い方:
  /category-search keyword:犬 ドライフード
  /category-search keyword:洗濯洗剤 mall:amazon
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SCRIPT = "/home/ubuntu/ec-automation-system/scripts/lookup_mall_categories.py"
TIMEOUT = 60

COLOR_WORKING = 0xF39C12
COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR = 0xE74C3C

MALL_CHOICES = [
    app_commands.Choice(name="全モール", value="all"),
    app_commands.Choice(name="楽天", value="rakuten"),
    app_commands.Choice(name="Amazon", value="amazon"),
    app_commands.Choice(name="Yahoo", value="yahoo"),
    app_commands.Choice(name="auPAY", value="aupay"),
    app_commands.Choice(name="Qoo10", value="qoo10"),
    app_commands.Choice(name="メルカリ", value="mercari"),
    app_commands.Choice(name="Temu", value="temu"),
]


class CategoryCommandCog(commands.Cog):
    """カテゴリ検索コマンド — 全7モールのカテゴリID一括検索."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="category-search",
        description="モールカテゴリ一括検索（全7モール対応）",
    )
    @app_commands.describe(
        keyword="検索キーワード（スペース区切りでAND検索）",
        mall="対象モール（未指定=全モール）",
    )
    @app_commands.choices(mall=MALL_CHOICES)
    async def category_search(
        self,
        interaction: discord.Interaction,
        keyword: str,
        mall: str = "all",
    ) -> None:
        """全7モールのカテゴリIDを一括検索."""
        keyword = keyword.strip()
        if not keyword:
            await interaction.response.send_message(
                "キーワードを入力してください。",
                ephemeral=True,
            )
            return

        # コマンド組み立て
        cmd = ["python3", SCRIPT]
        if mall != "all":
            cmd.extend(["--mall", mall])
        cmd.append(keyword)

        # 進捗表示
        mall_label = mall if mall != "all" else "全モール"
        embed = discord.Embed(
            title="カテゴリ検索中...",
            description=f"キーワード: **{keyword}** / モール: **{mall_label}**",
            color=COLOR_WORKING,
        )
        await interaction.response.send_message(embed=embed)

        # 実行
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd="/home/ubuntu/ec-automation-system",
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="タイムアウト",
                description="検索に時間がかかりすぎました。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("category-search command failed")
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
            # 出力を整形（Discord 4096文字制限対応）
            result_text = stdout_text.strip()
            if len(result_text) > 3900:
                result_text = result_text[:3900] + "\n... (省略)"

            embed = discord.Embed(
                title=f"カテゴリ検索結果: {keyword}",
                description=f"```\n{result_text}\n```",
                color=COLOR_SUCCESS,
            )
        else:
            err = stderr_text[:800] if stderr_text else stdout_text[:800] or "不明なエラー"
            embed = discord.Embed(
                title="カテゴリ検索エラー",
                description=f"```\n{err}\n```",
                color=COLOR_ERROR,
            )

        await interaction.edit_original_response(embed=embed)

        logger.info(
            "/category-search by %s: keyword=%s, mall=%s, rc=%s",
            interaction.user.name, keyword, mall, proc.returncode,
        )
