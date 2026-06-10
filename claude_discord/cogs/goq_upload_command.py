"""GoQ CSVアップロード Cog — /goq-upload でSS-08シート5〜11を一括GoQアップロード.

SS-08の在庫連携シート（Amazon1/2, Yahoo, auPAY, Qoo10, Temu）から
CSV/TSVを生成 → Google Drive保存 → n8n Webhook経由でGoQSystemに自動アップロード。

使い方:
  /goq-upload                    → シート5〜11一括アップロード
  /goq-upload mall:amazon1       → 特定モールのみ
  /goq-upload dry-run:True       → CSV生成のみ（アップロードしない）
"""

from __future__ import annotations

import asyncio
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SCRIPT = "/home/ubuntu/ec-automation-system/scripts/goq_upload.py"
SCRIPT_CWD = "/home/ubuntu/ec-automation-system"
TIMEOUT = 600  # 10分（全モール一括は時間かかる）

COLOR_WORKING = 0xF39C12  # オレンジ
COLOR_SUCCESS = 0x2ECC71  # 緑
COLOR_ERROR = 0xE74C3C  # 赤
COLOR_PARTIAL = 0xE67E22  # ダークオレンジ（一部失敗）

MALL_CHOICES = [
    app_commands.Choice(name="全モール一括", value="all"),
    app_commands.Choice(name="Amazon1", value="amazon1"),
    app_commands.Choice(name="Amazon2", value="amazon2"),
    app_commands.Choice(name="Yahoo", value="yahoo"),
    app_commands.Choice(name="auPAY", value="aupay"),
    app_commands.Choice(name="Qoo10(1)", value="qoo10_1"),
    app_commands.Choice(name="Temu", value="temu"),
]


class GoqUploadCommandCog(commands.Cog):
    """GoQ CSVアップロード — SS-08在庫連携シートをGoQに一括アップ."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="goq-upload",
        description="GoQ在庫連携CSVアップロード（SS-08シート5〜11→GoQ）",
    )
    @app_commands.describe(
        mall="対象モール（未指定=全モール一括）",
        dry_run="True=CSV生成のみ（GoQにはアップしない）",
    )
    @app_commands.choices(mall=MALL_CHOICES)
    async def goq_upload(
        self,
        interaction: discord.Interaction,
        mall: str = "all",
        dry_run: bool = False,
    ) -> None:
        """SS-08在庫連携シートをCSV化してGoQにアップロード."""
        mall_label = mall if mall != "all" else "全モール(5〜11)"
        mode = "dry-run（CSV生成のみ）" if dry_run else "GoQアップロード"

        embed = discord.Embed(
            title=f"GoQ CSVアップロード実行中...",
            description=f"モール: **{mall_label}**\nモード: {mode}",
            color=COLOR_WORKING,
        )
        embed.set_footer(text="SS-08 → CSV → Drive → n8n → GoQ")
        await interaction.response.send_message(embed=embed)

        # コマンド組み立て
        cmd = ["python3", SCRIPT, "--mall", mall, "--json"]
        if dry_run:
            cmd.append("--dry-run")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=SCRIPT_CWD,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="タイムアウト",
                description="処理に時間がかかりすぎました（10分超過）。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("goq-upload command failed")
            embed = discord.Embed(
                title="エラー",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        if proc.returncode is not None and proc.returncode <= 1:
            # JSON結果を抽出（stdout末尾のJSON配列）
            results = []
            try:
                # --json出力はstdout末尾にJSON配列がある
                json_start = stdout_text.rfind("\n[")
                if json_start >= 0:
                    results = json.loads(stdout_text[json_start:])
            except (json.JSONDecodeError, ValueError):
                pass

            if results:
                ok_count = sum(1 for r in results if r.get("ok"))
                ng_count = sum(1 for r in results if not r.get("ok"))
                total = len(results)

                if ng_count == 0:
                    color = COLOR_SUCCESS
                    title = f"GoQ CSVアップロード完了"
                elif ok_count == 0:
                    color = COLOR_ERROR
                    title = f"GoQ CSVアップロード失敗"
                else:
                    color = COLOR_PARTIAL
                    title = f"GoQ CSVアップロード一部失敗"

                embed = discord.Embed(
                    title=title,
                    description=f"**{ok_count}/{total}** モール成功",
                    color=color,
                )

                # 各モールの結果をフィールドに
                for r in results:
                    mark = "OK" if r.get("ok") else "NG"
                    rows = r.get("rows", 0)
                    msg = r.get("msg", "")
                    sheet = r.get("sheet", r.get("mall", "?"))
                    embed.add_field(
                        name=f"{'✅' if r.get('ok') else '❌'} {sheet}",
                        value=f"{rows}行 / {msg}" if rows else msg or "データなし",
                        inline=False,
                    )

                if dry_run:
                    embed.set_footer(text="dry-runモード: GoQへのアップロードは行っていません")
                else:
                    embed.set_footer(text="GoQへのアップロードはバックグラウンドで実行中。完了するとDiscordに通知されます")
            else:
                # JSON解析できなかった場合はテキスト出力
                lines = stdout_text.strip().split("\n")
                summary = "\n".join(ln.strip() for ln in lines[-15:] if ln.strip())
                embed = discord.Embed(
                    title="GoQ CSVアップロード完了",
                    description=f"```\n{summary[:1500]}\n```",
                    color=COLOR_SUCCESS if proc.returncode == 0 else COLOR_PARTIAL,
                )
        else:
            err = stderr_text[:800] if stderr_text else stdout_text[:800] or "不明なエラー"
            embed = discord.Embed(
                title="GoQ CSVアップロードエラー",
                description=f"```\n{err}\n```",
                color=COLOR_ERROR,
            )

        await interaction.edit_original_response(embed=embed)

        logger.info(
            "/goq-upload by %s: mall=%s, dry_run=%s, rc=%s",
            interaction.user.name, mall, dry_run, proc.returncode,
        )
