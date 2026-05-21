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
import time
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
    """bash コマンドを完全に分離して起動。PIDのみ返して結果は待たない。

    2層の分離で bot 再起動の影響を受けないようにする:
      1. systemd-run --user --scope: 独立 cgroup に配置（pkill/systemctl stop 耐性）
      2. start_new_session=True: 新セッション+プロセスグループ分離（SIGHUP 耐性）

    systemd-run が使えない環境では層2のみでフォールバック。
    bash ラッパー側でも trap '' HUP TERM を設定し、シグナル耐性を二重化。
    """
    # 層1: systemd-run --user --scope で独立 cgroup に配置
    try:
        scope_name = f"ec-batch-{os.getpid()}-{int(time.time())}"
        # ccdb bot は nohup 起動のため DBUS 環境変数が欠落しやすい → 明示補完
        uid = os.getuid()
        env = os.environ.copy()
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
        proc = await asyncio.create_subprocess_exec(
            "systemd-run", "--user", "--scope", f"--unit={scope_name}", "--",
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env=env,
            cwd=REPO_ROOT,
        )
        logger.info(f"バッチ起動(systemd scope={scope_name}): {' '.join(cmd[:3])}")
        return proc.pid
    except Exception as e:
        logger.warning(f"systemd-run --scope 失敗、フォールバック: {e}")

    # 層2: フォールバック（従来方式）
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
        start_new_session=True,
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
        force="LP_status が pending-lp 以外でも強制再生成（reason必須）",
        page="特定ページのみ再生成（1,3,4,5,6,7,8）。JAN1件のみ・reason必須",
        reason="force/page 指定時の理由（必須）",
    )
    @app_commands.choices(
        page=[
            app_commands.Choice(name="P1 (トップ)", value=1),
            app_commands.Choice(name="P3 (PASONA-P)", value=3),
            app_commands.Choice(name="P4 (PASONA-A)", value=4),
            app_commands.Choice(name="P5 (PASONA-S)", value=5),
            app_commands.Choice(name="P6 (PASONA-O)", value=6),
            app_commands.Choice(name="P7 (PASONA-N)", value=7),
            app_commands.Choice(name="P8 (PASONA-A)", value=8),
        ]
    )
    async def lp_command(
        self,
        interaction: discord.Interaction,
        jans: str,
        force: bool = False,
        page: app_commands.Choice[int] | None = None,
        reason: str | None = None,
    ) -> None:
        jan_list = _parse_jans(jans)
        if not jan_list:
            await interaction.response.send_message(
                "JANを13桁で指定してください。例: `4589980062377 4589980062384`",
                ephemeral=True,
            )
            return

        page_val = page.value if page else None

        # force/page 指定時は reason 必須
        if (force or page_val) and not (reason and reason.strip()):
            await interaction.response.send_message(
                "❌ `force:True` または `page` 指定時は `reason:\"理由\"` が必須です。",
                ephemeral=True,
            )
            return

        # page 指定時は JAN 1件のみ
        if page_val and len(jan_list) > 1:
            await interaction.response.send_message(
                "❌ `page` 指定時は JAN を1件のみ指定してください。",
                ephemeral=True,
            )
            return

        cmd: list[str] = ["bash", f"{REPO_ROOT}/scripts/lp_batch.sh"]
        if force or page_val:
            cmd.append("--force")
        if page_val:
            cmd.extend(["--page", str(page_val)])
        if reason and reason.strip():
            cmd.extend(["--reason", reason.strip()])
        cmd.extend(jan_list)

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

        # ページ指定は1ページ約2分、それ以外は1JAN約10分
        elapsed_est = 2 if page_val else len(jan_list) * 10
        title = "🔄 LP生成バッチ起動"
        if page_val:
            title = f"🔄 LP P{page_val} 単独再生成"
        elif force:
            title = "🔄 LP 強制再生成"

        desc_lines = [
            f"対象JAN: **{len(jan_list)}件**",
            f"処理時間目安: 約{elapsed_est}分",
        ]
        if force or page_val:
            desc_lines.append(f"理由: {reason}")
        desc_lines.append("進捗は <#1496390706304909332> で通知されます")
        desc_lines.append(f"PID: `{pid}`")

        embed = discord.Embed(
            title=title,
            description="\n".join(desc_lines),
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
        description="漫画LP生成（SS-03 pending-manga 全件・Python完結）",
    )
    async def manga_command(
        self,
        interaction: discord.Interaction,
    ) -> None:
        cmd = ["bash", f"{REPO_ROOT}/scripts/manga_batch.sh"]
        try:
            pid = await _spawn_detached(*cmd)
        except Exception as e:
            logger.exception("漫画LP生成バッチ起動失敗")
            embed = discord.Embed(
                title="漫画LP生成 起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🔄 漫画LP生成 開始",
            description=(
                "SS-03 K列 = `pending-manga` の全商品を脚本→リーガル→画像→SFTP の順で処理\n"
                "（Python完結 / 動物判定はVision白抜き画像優先）\n"
                f"進捗・完了通知は <#1496390706304909332> で\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /whitebg — 白抜き画像バッチ生成
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="whitebg",
        description="白抜き画像バッチ生成（JAN絞り込み・フォルダ指定・force/dry-run対応）",
    )
    @app_commands.describe(
        jans="JANコード（スペース区切り、13桁・複数指定可）。省略時はフォルダ全画像（最大250枚）",
        folder="入力DriveフォルダID or URL。省略時はデフォルト入力フォルダ",
        output_folder="出力DriveフォルダID or URL。省略時はデフォルト出力フォルダ（サムネ/LP入力）",
        force="処理済みファイルも上書きする",
        dry_run="一覧表示のみ（実処理しない）",
    )
    async def whitebg_command(
        self,
        interaction: discord.Interaction,
        jans: str = "",
        folder: str = "",
        output_folder: str = "",
        force: bool = False,
        dry_run: bool = False,
    ) -> None:
        jan_list = _parse_jans(jans) if jans else []

        cmd_parts = ["bash", f"{REPO_ROOT}/scripts/whitebg_batch.sh"]
        if folder:
            cmd_parts.extend(["--folder", folder])
        if output_folder:
            cmd_parts.extend(["--output-folder", output_folder])
        if force:
            cmd_parts.append("--force")
        if dry_run:
            cmd_parts.append("--dry-run")
        if jan_list:
            cmd_parts.extend(jan_list)

        try:
            pid = await _spawn_detached(*cmd_parts)
        except Exception as e:
            logger.exception("白抜き生成バッチ起動失敗")
            embed = discord.Embed(
                title="白抜き生成バッチ起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 処理時間目安: 1枚あたり約30秒（Gemini API + リトライ込み）
        if dry_run:
            target_label = "（dry-run: 一覧のみ）"
            elapsed_est = "数秒"
        elif jan_list:
            target_label = f"**{len(jan_list)}件** (JAN指定)"
            elapsed_est = f"約{len(jan_list) * 30 // 60 + 1}分"
        else:
            target_label = "フォルダ全画像（最大250枚）"
            elapsed_est = "数十分〜数時間（枚数次第）"

        # オプションラベル
        opts = []
        opts.append("入力:指定" if folder else "入力:デフォルト")
        if output_folder:
            opts.append("出力:指定")
        if force:
            opts.append("force=ON")
        if dry_run:
            opts.append("dry-run=ON")

        embed = discord.Embed(
            title="🔄 白抜き生成バッチ起動",
            description=(
                f"対象: {target_label}\n"
                f"処理時間目安: {elapsed_est}\n"
                f"オプション: {' / '.join(opts)}\n"
                f"進捗は <#1496390706304909332> で通知されます\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        if jan_list:
            embed.add_field(
                name="JAN一覧",
                value="\n".join(f"• `{j}`" for j in jan_list[:20])
                + (f"\n…他{len(jan_list)-20}件" if len(jan_list) > 20 else ""),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /prepare — SS-03 画像生成データ準備
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="prepare",
        description="SS-03 画像生成データ準備（Drive白抜き画像→SS-03 pending登録）",
    )
    @app_commands.describe(
        shop="対象店舗（デフォルト mofu）",
        dry_run="一覧表示のみ（実処理しない）",
    )
    @app_commands.choices(
        shop=[
            app_commands.Choice(name="mofu", value="mofu"),
            app_commands.Choice(name="fdmart", value="fdmart"),
            app_commands.Choice(name="both（mofu→fdmart）", value="both"),
        ]
    )
    async def prepare_command(
        self,
        interaction: discord.Interaction,
        shop: app_commands.Choice[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        shop_val = shop.value if shop else "mofu"
        cmd_parts = ["bash", f"{REPO_ROOT}/scripts/prepare_images_batch.sh", "--shop", shop_val]
        if dry_run:
            cmd_parts.append("--dry-run")

        try:
            pid = await _spawn_detached(*cmd_parts)
        except Exception as e:
            logger.exception("SS-03準備バッチ起動失敗")
            embed = discord.Embed(
                title="SS-03準備バッチ起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🔄 SS-03 画像生成データ準備起動",
            description=(
                f"店舗: **{shop_val}**\n"
                f"モード: {'dry-run（一覧のみ）' if dry_run else '本実行'}\n"
                f"処理時間目安: 数秒〜数十秒\n"
                f"進捗は <#1496390706304909332> で通知されます\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /archive — SS-03 完了行アーカイブ
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="archive",
        description="SS-03 完了行アーカイブ（done行を完了シートに移動）",
    )
    @app_commands.describe(
        shop="対象店舗（デフォルト mofu）",
        dry_run="一覧表示のみ（実処理しない）",
    )
    @app_commands.choices(
        shop=[
            app_commands.Choice(name="mofu", value="mofu"),
            app_commands.Choice(name="fdmart", value="fdmart"),
            app_commands.Choice(name="both（mofu→fdmart）", value="both"),
        ]
    )
    async def archive_command(
        self,
        interaction: discord.Interaction,
        shop: app_commands.Choice[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        shop_val = shop.value if shop else "mofu"
        cmd_parts = ["bash", f"{REPO_ROOT}/scripts/archive_done_batch.sh", "--shop", shop_val]
        if dry_run:
            cmd_parts.append("--dry-run")

        try:
            pid = await _spawn_detached(*cmd_parts)
        except Exception as e:
            logger.exception("SS-03アーカイブバッチ起動失敗")
            embed = discord.Embed(
                title="SS-03アーカイブバッチ起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🔄 SS-03 完了行アーカイブ起動",
            description=(
                f"店舗: **{shop_val}**\n"
                f"モード: {'dry-run（一覧のみ）' if dry_run else '本実行'}\n"
                f"処理時間目安: 数秒〜数十秒\n"
                f"進捗は <#1496390706304909332> で通知されます\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    # /sp_dimensions — SP-API パッケージ寸法補完
    # ─────────────────────────────────────────────

    @app_commands.command(
        name="sp_dimensions",
        description="SP-API パッケージ寸法をSS-08 V〜Y列に書き込み（行範囲指定）",
    )
    @app_commands.describe(
        start_row="開始行（デフォルト241）",
        end_row="終了行（デフォルト290）",
    )
    async def sp_dimensions_command(
        self,
        interaction: discord.Interaction,
        start_row: int = 241,
        end_row: int = 290,
    ) -> None:
        if end_row < start_row:
            await interaction.response.send_message(
                f"end_row ({end_row}) は start_row ({start_row}) 以上を指定してください",
                ephemeral=True,
            )
            return

        cmd_parts = [
            "bash",
            f"{REPO_ROOT}/scripts/sp_dimensions_batch.sh",
            str(start_row),
            str(end_row),
        ]
        try:
            pid = await _spawn_detached(*cmd_parts)
        except Exception as e:
            logger.exception("SP-API寸法補完バッチ起動失敗")
            embed = discord.Embed(
                title="SP-API寸法補完バッチ起動失敗",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        rows = end_row - start_row + 1
        # 1行あたり SP-API 1回呼び出し ≒ 2秒
        elapsed_est = max(1, rows * 2 // 60)

        embed = discord.Embed(
            title="🔄 SP-API 寸法補完バッチ起動",
            description=(
                f"対象行: **{start_row} 〜 {end_row}**（{rows}行）\n"
                f"処理時間目安: 約{elapsed_est}分\n"
                f"進捗は <#1496390706304909332> で通知されます\n"
                f"PID: `{pid}`"
            ),
            color=COLOR_STARTED,
        )
        await interaction.response.send_message(embed=embed)
