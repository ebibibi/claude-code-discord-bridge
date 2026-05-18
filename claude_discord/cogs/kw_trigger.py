"""KW調査トリガー Cog — Discordからn8n KW WFをワンコマンドで起動.

/kw <商品名>   → A12 新商品KW調査（Apify B1→Sonnet市場分析→Discord通知）
/kw-opt        → A11 既存品KW最適化（SS-08対象商品→B1→Sonnet→SS-08書込）

n8n Webhookを直接叩くだけの軽量コマンド。
結果はn8n WF内のDiscord Webhookノードから5-6分後に届く。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# n8n Webhook URLs
N8N_BASE = "https://takaenterprise.app.n8n.cloud/webhook"
A12_WEBHOOK_PATH = "a12-new-product-kw"
A11_WEBHOOK_PATH = "a11-kw-optimize"

# Embed colors
COLOR_STARTED = 0x3498DB   # 青
COLOR_ERROR = 0xE74C3C     # 赤


class KwTriggerCog(commands.Cog):
    """KW調査コマンド — n8n WF Webhookトリガー."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="kw",
        description="新商品KW調査（商品名→市場分析→参入判断）",
    )
    @app_commands.describe(
        product_name="商品名 or シードKW（例: 粟の穂, ペットフード 犬 おやつ）",
        brand="ブランド名（省略可）",
        seed_kw="シードKW（省略可。指定するとこれでB1検索）",
    )
    async def kw_new(
        self,
        interaction: discord.Interaction,
        product_name: str,
        brand: str = "",
        seed_kw: str = "",
    ) -> None:
        """A12 新商品KW調査をn8n Webhookで起動."""
        product_name = product_name.strip()
        if not product_name or len(product_name) < 2:
            await interaction.response.send_message(
                "商品名を2文字以上入力してください。", ephemeral=True
            )
            return

        await interaction.response.defer()

        payload = {
            "product_name": product_name,
            "brand_name": brand.strip(),
            "seed_kw": seed_kw.strip() or product_name,
        }

        url = f"{N8N_BASE}/{A12_WEBHOOK_PATH}"
        success = await self._call_webhook(url, payload)

        embed = discord.Embed(
            title="KW調査開始" if success else "エラー",
            color=COLOR_STARTED if success else COLOR_ERROR,
        )

        if success:
            embed.description = (
                f"**{product_name}** の新商品KW調査を開始しました。\n"
                f"Apify B1 → Sonnet市場分析 → 結果通知まで約5-6分。\n\n"
                f"シードKW: `{seed_kw or product_name}`"
            )
            if brand:
                embed.add_field(name="ブランド", value=brand, inline=True)
        else:
            embed.description = "n8n Webhookの呼び出しに失敗しました。WFがactiveか確認してください。"

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="kw-opt",
        description="既存品KW最適化（SS-08の対象商品を一括処理）",
    )
    async def kw_optimize(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """A11 既存品KW最適化をn8n Webhookで起動."""
        await interaction.response.defer()

        url = f"{N8N_BASE}/{A11_WEBHOOK_PATH}"
        success = await self._call_webhook(url, {})

        embed = discord.Embed(
            title="KW最適化開始" if success else "エラー",
            color=COLOR_STARTED if success else COLOR_ERROR,
        )

        if success:
            embed.description = (
                "SS-08「KW最適化=対象」の商品を一括処理します。\n"
                "Apify B1 → Sonnet生成 → SS-08書込 → 結果通知まで約5-6分。"
            )
        else:
            embed.description = "n8n Webhookの呼び出しに失敗しました。WFがactiveか確認してください。"

        await interaction.followup.send(embed=embed)

    async def _call_webhook(self, url: str, payload: dict) -> bool:
        """n8n WebhookをPOSTで呼び出す。成功でTrue."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    logger.info("n8n webhook %s → %d", url, resp.status)
                    return resp.status == 200
        except Exception:
            logger.exception("n8n webhook call failed: %s", url)
            return False
