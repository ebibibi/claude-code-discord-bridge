"""商品マスター検索 Cog — JANコードや商品名でSS-01/SS-07を横断検索.

全従業員が使える読み取り専用の商品情報検索コマンド。
/shohin ビスカル → 商品名・原価・売価・利益率・仕入先を表示。

内部で ec-automation-system/scripts/shohin_search.py を呼び出す。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 検索スクリプトのパス
SEARCH_SCRIPT = "/home/ubuntu/ec-automation-system/scripts/shohin_search.py"
SEARCH_TIMEOUT = 30  # 秒

# Embed カラー
COLOR_FOUND = 0x2ECC71  # 緑
COLOR_NOT_FOUND = 0xE74C3C  # 赤
COLOR_SEARCHING = 0x3498DB  # 青


class ShohinSearchCog(commands.Cog):
    """商品マスター検索 — JANコードor商品名で即座に情報を返す."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="shohin",
        description="商品マスター検索（JAN or 商品名）",
    )
    @app_commands.describe(
        query="JANコード or 商品名キーワード（例: ビスカル, 4972468011293）"
    )
    async def shohin_search(
        self,
        interaction: discord.Interaction,
        query: str,
    ) -> None:
        """商品マスターを検索して結果をEmbed形式で表示."""
        # 入力バリデーション
        query = query.strip()
        if not query or len(query) < 2:
            await interaction.response.send_message(
                "検索キーワードを2文字以上入力してください。",
                ephemeral=True,
            )
            return

        # 検索中の表示
        embed = discord.Embed(
            title="検索中...",
            description=f"`{query}` を商品マスターから検索しています",
            color=COLOR_SEARCHING,
        )
        await interaction.response.send_message(embed=embed)

        try:
            # shohin_search.py を --json モードで実行
            proc = await asyncio.create_subprocess_exec(
                "python3",
                SEARCH_SCRIPT,
                "--json",
                "--max", "5",
                query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=SEARCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="タイムアウト",
                description="検索に時間がかかりすぎました。もう一度お試しください。",
                color=COLOR_NOT_FOUND,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("shohin_search failed")
            embed = discord.Embed(
                title="エラー",
                description=f"検索中にエラーが発生しました: {e}",
                color=COLOR_NOT_FOUND,
            )
            await interaction.edit_original_response(embed=embed)
            return

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            embed = discord.Embed(
                title="検索エラー",
                description=f"```\n{err[:500]}\n```",
                color=COLOR_NOT_FOUND,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # JSON結果をパース
        try:
            results = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            embed = discord.Embed(
                title="パースエラー",
                description="検索結果の解析に失敗しました。",
                color=COLOR_NOT_FOUND,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # 結果なし
        if not results:
            embed = discord.Embed(
                title="該当なし",
                description=f"「{query}」に一致する商品が見つかりませんでした。",
                color=COLOR_NOT_FOUND,
            )
            embed.set_footer(text="商品名・JANコード・メーカー名で検索できます")
            await interaction.edit_original_response(embed=embed)
            return

        # 結果を Embed 形式で表示
        embeds = []
        for i, r in enumerate(results):
            name = r.get("name", "不明")
            spec = r.get("spec", "")
            title = f"{name}" + (f"  ({spec})" if spec else "")

            embed = discord.Embed(
                title=title,
                color=COLOR_FOUND,
            )

            # 基本情報
            basic_lines = []
            if r.get("jan"):
                basic_lines.append(f"**JAN:** `{r['jan']}`")
            basic_lines.append(f"**部門:** {r.get('bumon', '-')}")
            if r.get("maker"):
                basic_lines.append(f"**メーカー:** {r['maker']}")
            if r.get("brand"):
                basic_lines.append(f"**ブランド:** {r['brand']}")
            if r.get("shiresaki"):
                basic_lines.append(f"**仕入先:** {r['shiresaki']}")

            embed.add_field(
                name="基本情報",
                value="\n".join(basic_lines),
                inline=True,
            )

            # 価格情報
            price_lines = []
            if r.get("genka_nozei"):
                price_lines.append(f"**原価(税抜):** ¥{r['genka_nozei']}")
            if r.get("genka_zeikomi"):
                price_lines.append(f"**原価(税込):** ¥{r['genka_zeikomi']}")
            if r.get("rakuten_price"):
                price_lines.append(f"**楽天売価:** ¥{r['rakuten_price']}")
            if r.get("amazon_price"):
                price_lines.append(f"**Amazon売価:** ¥{r['amazon_price']}")
            if r.get("rieki"):
                price_lines.append(f"**利益率:** {r['rieki']}")

            if price_lines:
                embed.add_field(
                    name="価格・利益",
                    value="\n".join(price_lines),
                    inline=True,
                )
            else:
                embed.add_field(
                    name="価格・利益",
                    value="原価: ¥" + r.get("genka_nozei", "-") + "\n*(売価・利益率は未設定)*",
                    inline=True,
                )

            # ステータス
            status = r.get("status", "")
            if status:
                status_emoji = "✅" if status == "取扱中" else "⛔"
                embed.set_footer(text=f"{status_emoji} {status}")

            embeds.append(embed)

        # ヘッダー embed
        header = discord.Embed(
            description=f"🔍 **{query}** の検索結果: **{len(results)}件**"
            + (" (最大5件表示)" if len(results) >= 5 else ""),
            color=COLOR_SEARCHING,
        )
        embeds.insert(0, header)

        # Discord は1メッセージ最大10 embeds
        await interaction.edit_original_response(embeds=embeds[:10])

        logger.info(
            "/shohin by %s: query=%r, results=%d",
            interaction.user.name,
            query,
            len(results),
        )
