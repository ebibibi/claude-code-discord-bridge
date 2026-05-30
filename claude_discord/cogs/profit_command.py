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
        description="社内SKU/JAN+モール+売価から利益率を算出（売価−原価−手数料−送料、広告費除外）",
    )
    @app_commands.describe(
        mall="モール（手数料率計算用）",
        sku="社内SKU（<JAN>-<配送番号>-<個数>形式）または JAN コード",
        price="売価（円）",
    )
    @app_commands.choices(
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
        mall: str,
        sku: str,
        price: float,
    ) -> None:
        """利益率算出コマンド."""
        if price <= 0:
            await interaction.response.send_message(
                "売価（price）は1以上を指定してください。", ephemeral=True
            )
            return
        cmd = ["python3", SCRIPT, "jan", sku, "--mall", mall, "--price", str(price)]
        title = f"利益率確認中... SKU: {sku} / {mall} / ¥{int(price):,}"

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
