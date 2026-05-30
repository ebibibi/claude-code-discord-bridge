"""利益率確認コマンド Cog — /profit で社内SKU/JAN+モール+売価から利益率を算出.

社内SKUは全モール共通の <JAN>-<配送番号>-<個数> 形式（例: 4972228232401-hk-1）。
SKU から JAN は自動抽出（先頭の "-" まで）。JAN直接入力も可。

使い方:
  /profit mall:楽天 sku:4972228232401-hk-1 price:1980
  /profit mall:Amazon sku:4972228232005 price:2480
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
        description="利益率算出（SKU）or マスタ表示（手数料/配送/FBA手数料）",
    )
    @app_commands.describe(
        sku="【利益率】社内SKU（例: 4972228232401-hk-1）または JAN",
        shop="【利益率】特定店舗のみ表示する場合に指定",
        master="【マスタ表示】表示するマスタ種別",
        mall="【マスタ表示】手数料マスタのモール絞り込み",
    )
    @app_commands.choices(
        master=[
            app_commands.Choice(name="🏷️ 手数料マスタ", value="fee"),
            app_commands.Choice(name="🚚 配送マスタ", value="shipping"),
            app_commands.Choice(name="📦 FBA手数料マスタ", value="fba"),
        ],
        mall=[
            app_commands.Choice(name="楽天", value="楽天"),
            app_commands.Choice(name="Amazon", value="Amazon"),
            app_commands.Choice(name="Yahoo", value="Yahoo"),
            app_commands.Choice(name="auPAY", value="auPAY"),
            app_commands.Choice(name="Qoo10", value="Qoo10"),
            app_commands.Choice(name="Temu", value="Temu"),
            app_commands.Choice(name="メルカリ", value="メルカリ"),
        ],
    )
    async def profit(
        self,
        interaction: discord.Interaction,
        sku: str = "",
        shop: str = "",
        master: str = "",
        mall: str = "",
    ) -> None:
        """利益率算出 or マスタ表示."""
        if master:
            cmd = ["python3", SCRIPT, "master", master]
            if mall:
                cmd.extend(["--mall", mall])
            mname = {
                "fee": "🏷️ 手数料マスタ",
                "shipping": "🚚 配送マスタ",
                "fba": "📦 FBA手数料マスタ",
            }.get(master, master)
            title = f"{mname} 取得中..." + (f" ({mall})" if mall else "")
        elif sku:
            cmd = ["python3", SCRIPT, "sku", sku]
            if shop:
                cmd.extend(["--shop", shop])
            title = f"利益率確認中... SKU: {sku}" + (
                f" / 店舗: {shop}" if shop else " (全店舗)"
            )
        else:
            await interaction.response.send_message(
                "`sku`（利益率モード）または `master`（マスタ表示モード）のいずれかを指定してください。",
                ephemeral=True,
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
                # stdout / stderr 両方表示（stderr に Warning だけ出る場合があるため）
                parts: list[str] = []
                if out.strip():
                    parts.append(f"[stdout]\n{out.strip()}")
                if err.strip():
                    parts.append(f"[stderr]\n{err.strip()}")
                detail = "\n\n".join(parts) or "(出力なし)"
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
