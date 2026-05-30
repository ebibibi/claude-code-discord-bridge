"""利益率確認コマンド Cog — /profit でモール固有SKU/JANから利益率を算出.

使い方:
  /profit mall:楽天 sku:<管理番号> store:mofu
  /profit mall:Amazon sku:<SKU> account:1
  /profit mall:JAN sku:<JAN> price:1980
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SCRIPT = "/home/ubuntu/ec-automation-system/scripts/profit_check.py"
SCRIPT_CWD = "/home/ubuntu/ec-automation-system"
ENV_FILE = "/home/ubuntu/ec-automation-system/scripts/.env"
TIMEOUT = 60

COLOR_WORKING = 0xF39C12
COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR = 0xE74C3C


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


class ProfitCommandCog(commands.Cog):
    """利益率確認 — モール固有SKU/JAN から利益率を算出."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="profit",
        description="モール固有SKU/JANから利益率を算出（売価−原価−手数料−送料、広告費は除外）",
    )
    @app_commands.describe(
        mall="モール種別",
        sku="モール固有SKU（楽天=管理番号 / Amazon=SKU / JAN モード=JANコード）",
        store="楽天のみ：店舗",
        account="Amazonのみ：アカウント",
        price="JANモード時の売価（円）",
        jan_mall="JANモード時のモール（手数料率計算用）",
    )
    @app_commands.choices(
        mall=[
            app_commands.Choice(name="楽天", value="rakuten"),
            app_commands.Choice(name="Amazon", value="amazon"),
            app_commands.Choice(name="JAN直接指定（売価手入力）", value="jan"),
        ],
        store=[
            app_commands.Choice(name="うちのmofu", value="mofu"),
            app_commands.Choice(name="fanddmart", value="fanddmart"),
        ],
        account=[
            app_commands.Choice(name="a1 (タカエンタープライズ)", value=1),
            app_commands.Choice(name="a2 (日用品生活ショップ)", value=2),
        ],
        jan_mall=[
            app_commands.Choice(name="楽天", value="楽天"),
            app_commands.Choice(name="Amazon", value="Amazon"),
            app_commands.Choice(name="Yahoo", value="Yahoo"),
            app_commands.Choice(name="auPAY", value="auPAY"),
            app_commands.Choice(name="Qoo10", value="Qoo10"),
            app_commands.Choice(name="Temu", value="Temu"),
        ],
    )
    async def profit(
        self,
        interaction: discord.Interaction,
        mall: str,
        sku: str,
        store: str = "mofu",
        account: int = 1,
        price: float = 0.0,
        jan_mall: str = "楽天",
    ) -> None:
        """利益率算出コマンド."""
        cmd = ["python3", SCRIPT]

        if mall == "rakuten":
            cmd.extend(["rakuten", sku, "--store", store])
            title = f"楽天 利益率確認中... SKU: {sku}"
        elif mall == "amazon":
            cmd.extend(["amazon", sku, "--account", str(account)])
            title = f"Amazon 利益率確認中... SKU: {sku}"
        elif mall == "jan":
            if not price or price <= 0:
                await interaction.response.send_message(
                    "JANモードでは price（売価）を指定してください。",
                    ephemeral=True,
                )
                return
            cmd.extend(["jan", sku, "--mall", jan_mall, "--price", str(price)])
            title = f"JAN 利益率確認中... JAN: {sku} / モール: {jan_mall}"
        else:
            await interaction.response.send_message(
                "不明なモールです。", ephemeral=True
            )
            return

        embed = discord.Embed(title=title, color=COLOR_WORKING)
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=SCRIPT_CWD,
                env=_build_subprocess_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT
            )
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                body = out.strip() if out.strip() else "(出力なし)"
                result_embed = discord.Embed(
                    title="✅ 利益率算出完了",
                    description=f"```\n{body[:1800]}\n```",
                    color=COLOR_SUCCESS,
                )
            else:
                detail = (err or out).strip() or "(出力なし)"
                result_embed = discord.Embed(
                    title=f"❌ エラー (exit={proc.returncode})",
                    description=f"```\n{detail[:1800]}\n```",
                    color=COLOR_ERROR,
                )
            await msg.edit(embed=result_embed)

        except asyncio.TimeoutError:
            await msg.edit(
                embed=discord.Embed(
                    title="❌ タイムアウト",
                    description=f"{TIMEOUT}秒以内に完了しませんでした。",
                    color=COLOR_ERROR,
                )
            )
        except Exception as e:
            logger.exception("profit command failed")
            await msg.edit(
                embed=discord.Embed(
                    title="❌ 例外",
                    description=str(e)[:1800],
                    color=COLOR_ERROR,
                )
            )
