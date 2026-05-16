"""画像生成バッチコマンド Cog — /lp /thumbnail /manga.

LP/サムネ/漫画LPの3スキルバッチをDiscord slash commandで起動できる。
shohin_search.py と同じパターンで実装（Claude Code を介さず、bash ラッパーを
asyncio.subprocess で detach 起動。長時間処理 (90分等) なので結果は待たず、
進捗・完了通知は bash ラッパー側の notify_image_gen が #画像生成 ch に投げる）。

Usage:
    /lp jans:"4589980062377 4589980062384"
    /thumbnail jans:"4589980062377 4589980062384" batch_api:True
    /manga
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# bash ラッパーの場所
REPO_ROOT = "/home/ubuntu/ec-automation-system"

# Embed カラー
COLOR_STARTED = 0x3498DB  # 青
COLOR_ERROR = 0xE74C3C  # 赤

# JAN13桁を抽出する正規表現
_JAN_RE = re.compile(r"\d{13}")


def _parse_jans(text: str) -> list[str]:
    """テキストからJAN13桁を抽出（スペース・カンマ等の区切り文字無視）。"""
    return _JAN_RE.findall(text)


async def _spawn_detached(*cmd: str) -> int:
    """bash コマンドを detach 起動。PIDのみ返して結果は待たない。

    nohup 相当の挙動: 親プロセスが終了しても継続実行。
    stdout/stderr は捨てる（ログは bash ラッパー側のログファイルに残る）。
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
        start_new_session=True,  # 新セッションでプロセスグループ分離
        cwd=REPO_ROOT,
    )
    return proc.pid


class ImageGenCommandCog(commands.Cog):
    """画像生成バッチコマンド: /lp /thumbnail /manga."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ─────────────────────────────────────────────
    # /lp — LP画像バッチ生成
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="lp",
        description="LP画像バッチ生成（複数JAN・両店舗・SFTP込み）",
    )
    @app_commands.describe(
        jans="JANコード（スペース区切り、13桁・複数指定可）",
    )
    async def lp_command(
        self,
        interaction: discord.Interaction,
        jans: str,
    ) -> None:
        jan_list = _parse_jans(jans)
        if not jan_list:
            await interaction.response.send_message(
                "JANを13桁で指定してください。例: `4589980062377 4589980062384`",
                ephemeral=True,
            )
            return

        cmd = [
            "bash",
            f"{REPO_ROOT}/scripts/lp_batch.sh",
            *jan_list,
        ]

        try:
            pid = await _spawn_detached(*cmd)
        except Exception as e:
            logger.exception("LP生成バッチ起動失敗")
            embed = discord.Embed(
                title="LP生成バッチ起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        elapsed_est = len(jan_list) * 10  # 1JAN ≒ 10分
        embed = discord.Embed(
            title="🔄 LP生成バッチ起動",
            description=(
                f"対象JAN: **{len(jan_list)}件**\n"
                f"処理時間目安: 約{elapsed_est}分\n"
                f"進捗は <#1496390706304909332> で通知されます\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        embed.add_field(
            name="JAN一覧",
            value="\n".join(f"• `{j}`" for j in jan_list[:20])
            + (f"\n…他{len(jan_list)-20}件" if len(jan_list) > 20 else ""),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /thumbnail — サムネイル画像バッチ生成
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="thumbnail",
        description="サムネイル画像バッチ生成（複数JAN・両店舗）",
    )
    @app_commands.describe(
        jans="JANコード（スペース区切り、13桁・複数指定可）",
        batch_api="Batch APIモードで実行（50%OFF・30〜60分待ち）",
        shop="対象店舗（指定しない場合は両方）",
    )
    @app_commands.choices(
        shop=[
            app_commands.Choice(name="両方（mofu→fdmart）", value="both"),
            app_commands.Choice(name="mofu のみ", value="mofu"),
            app_commands.Choice(name="fdmart のみ", value="fdmart"),
        ]
    )
    async def thumbnail_command(
        self,
        interaction: discord.Interaction,
        jans: str,
        batch_api: bool = False,
        shop: app_commands.Choice[str] | None = None,
    ) -> None:
        jan_list = _parse_jans(jans)
        if not jan_list:
            await interaction.response.send_message(
                "JANを13桁で指定してください。例: `4589980062377 4589980062384`",
                ephemeral=True,
            )
            return

        cmd_parts = [
            "bash",
            f"{REPO_ROOT}/scripts/thumbnail_batch.sh",
        ]
        if shop:
            cmd_parts.extend(["--shop", shop.value])
        if batch_api:
            cmd_parts.append("--batch-api")
        cmd_parts.extend(jan_list)

        try:
            pid = await _spawn_detached(*cmd_parts)
        except Exception as e:
            logger.exception("サムネ生成バッチ起動失敗")
            embed = discord.Embed(
                title="サムネ生成バッチ起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        mode = "Batch API (50%OFF)" if batch_api else "通常モード"
        shop_label = shop.name if shop else "両方"
        embed = discord.Embed(
            title="🔄 サムネ生成バッチ起動",
            description=(
                f"対象JAN: **{len(jan_list)}件**\n"
                f"店舗: {shop_label}\n"
                f"モード: {mode}\n"
                f"進捗は <#1496390706304909332> で通知されます\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /manga — 漫画LP生成バッチ
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="manga",
        description="漫画LP生成（SS-03 pending-manga 全件・n8n WFトリガ）",
    )
    async def manga_command(
        self,
        interaction: discord.Interaction,
    ) -> None:
        cmd = ["bash", f"{REPO_ROOT}/scripts/manga_batch.sh"]
        try:
            pid = await _spawn_detached(*cmd)
        except Exception as e:
            logger.exception("漫画LP生成トリガ失敗")
            embed = discord.Embed(
                title="漫画LP生成トリガ失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🔄 漫画LP生成トリガ送信",
            description=(
                "SS-03 K列 = `pending-manga` の全商品を A5a_漫画リーガル WF で処理\n"
                f"進捗・完了通知は <#1496390706304909332> で\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        await interaction.response.send_message(embed=embed)
