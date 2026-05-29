"""出品コマンド Cog — /shuppin でモール出品.

SS-17「出品データ」を唯一のデータソースとし、指定モールに出品する。
JAN未指定=未出品JAN全部、JAN指定=バリエーション自動展開。

使い方:
  /shuppin mall:Yahoo                   → 未出品JAN全部をYahooに出品
  /shuppin mall:Amazon jan:4562305934023 → そのJAN+バリエーション全部をAmazonに出品
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# バックエンドスクリプト
PIPELINE_SCRIPT = "/home/ubuntu/ec-automation-system/scripts/shuppin_pipeline.py"
PREVIEW_TIMEOUT = 60
SUBMIT_TIMEOUT = 600  # バリエーション一括出品は時間がかかる
SUBMIT_TIMEOUT_ALL = 900  # 全モール一括出品時

# Embed カラー
COLOR_PREVIEW = 0x3498DB   # 青
COLOR_SUCCESS = 0x2ECC71   # 緑
COLOR_ERROR = 0xE74C3C     # 赤
COLOR_CANCEL = 0x95A5A6    # グレー
COLOR_WORKING = 0xF39C12   # オレンジ

# 1人1ロック
_active_locks: dict[int, str] = {}


def _load_allowed_user_ids() -> set[int] | None:
    """SHUPPIN_ALLOWED_USER_IDS 環境変数からユーザーIDセットを取得."""
    raw = os.getenv("SHUPPIN_ALLOWED_USER_IDS", "")
    if raw.strip() == "*":
        return None

    ids: set[int] = set()
    if raw.strip():
        for uid in raw.split(","):
            uid = uid.strip()
            if uid.isdigit():
                ids.add(int(uid))

    owner = os.getenv("DISCORD_OWNER_ID", "")
    if owner.strip().isdigit():
        ids.add(int(owner.strip()))

    return ids if ids else None


class ListingConfirmView(discord.ui.View):
    """出品確認ボタン（出品する / やめる / ドライラン）"""

    def __init__(self, user_id: int, mall: str, jan: str | None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.mall = mall
        self.jan = jan
        self.result: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このボタンは操作できません。", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="出品する", style=discord.ButtonStyle.success, emoji="\u2705")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "confirm"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.danger, emoji="\u274C")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "cancel"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="ドライラン", style=discord.ButtonStyle.secondary, emoji="\U0001F9EA")
    async def dry_run(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "dry_run"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self):
        self.result = "timeout"
        self.stop()


class ListingCommandCog(commands.Cog):
    """出品コマンド — SS-17ベースでモール出品."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._allowed_user_ids = _load_allowed_user_ids()
        if self._allowed_user_ids is not None:
            logger.info(
                "ListingCommandCog: allowed users = %s",
                ", ".join(str(uid) for uid in self._allowed_user_ids),
            )
        else:
            logger.info("ListingCommandCog: all users allowed")

    @app_commands.command(
        name="shuppin",
        description="SS-17ベースでモール出品（JAN未指定=未出品全部、指定=バリエーション展開）",
    )
    @app_commands.describe(
        mall="出品先モール（必須）",
        jan="JAN（任意: 未指定=未出品JAN全部、指定=バリエーション展開）",
    )
    @app_commands.choices(mall=[
        app_commands.Choice(name="ALL SHOP（全モール）", value="all"),
        app_commands.Choice(name="Amazon", value="amazon"),
        app_commands.Choice(name="Yahoo", value="yahoo"),
        app_commands.Choice(name="Qoo10", value="qoo10"),
        app_commands.Choice(name="auPAY", value="aupay"),
        app_commands.Choice(name="Temu", value="temu"),
        app_commands.Choice(name="メルカリ", value="mercari"),
    ])
    async def shuppin(
        self,
        interaction: discord.Interaction,
        mall: str,
        jan: str = "",
    ) -> None:
        """SS-17ベースでモール出品."""
        user_id = interaction.user.id

        # ユーザー権限チェック
        if self._allowed_user_ids is not None and user_id not in self._allowed_user_ids:
            await interaction.response.send_message(
                "このコマンドの使用権限がありません。管理者に連絡してください。",
                ephemeral=True,
            )
            return

        jan = jan.strip() if jan else ""

        # JANバリデーション（指定された場合のみ）
        if jan and (not jan.isdigit() or len(jan) not in (8, 13)):
            await interaction.response.send_message(
                "JANコードは8桁または13桁の数字で入力してください。",
                ephemeral=True,
            )
            return

        # 1ロックチェック
        lock_key = f"{mall}"
        if user_id in _active_locks:
            locked = _active_locks[user_id]
            await interaction.response.send_message(
                f"前の出品処理（{locked}）が進行中です。\n"
                "完了またはキャンセルしてから次を入力してください。",
                ephemeral=True,
            )
            return

        _active_locks[user_id] = f"{mall}" + (f" JAN:{jan}" if jan else " 未出品全部")

        try:
            await self._process_listing(interaction, mall, jan or None, user_id)
        finally:
            _active_locks.pop(user_id, None)

    async def _process_listing(
        self,
        interaction: discord.Interaction,
        mall: str,
        jan: str | None,
        user_id: int,
    ) -> None:
        """出品フローのメイン処理"""

        # Step 1: プレビュー表示
        jan_label = f"JAN: `{jan}` (バリエーション展開)" if jan else "未出品JAN全部"
        embed = discord.Embed(
            title=f"{mall.upper()} 出品準備中...",
            description=f"対象: {jan_label}",
            color=COLOR_WORKING,
        )
        await interaction.response.send_message(embed=embed)

        # Step 2: JAN指定時はプレビュー取得
        if jan:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", PIPELINE_SCRIPT,
                    "preview", "--jan", jan,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=PREVIEW_TIMEOUT
                )
            except asyncio.TimeoutError:
                embed = discord.Embed(
                    title="タイムアウト",
                    description="商品情報の取得に時間がかかりすぎました。",
                    color=COLOR_ERROR,
                )
                await interaction.edit_original_response(embed=embed)
                return
            except Exception as e:
                logger.exception("shuppin preview failed")
                embed = discord.Embed(
                    title="エラー",
                    description=f"プレビュー取得に失敗: {e}",
                    color=COLOR_ERROR,
                )
                await interaction.edit_original_response(embed=embed)
                return

            if proc.returncode == 0:
                try:
                    data = json.loads(stdout.decode("utf-8"))
                    product = data.get("product", {})
                    product_name = product.get("name") or f"JAN: {jan}"
                    price = product.get("price", "?")
                    has_images = product.get("has_images", False)
                    has_desc = product.get("has_description", False)

                    # モール別カテゴリID有無
                    cat_status = []
                    for cat_key, cat_label in [
                        ("qoo10_category", "Qoo10"),
                        ("amazon_browse_node", "Amazon"),
                        ("yahoo_category", "Yahoo"),
                        ("aupay_category", "auPAY"),
                    ]:
                        val = product.get(cat_key, "")
                        cat_status.append(f"{cat_label}:{'OK' if val else 'NG'}")

                    embed = discord.Embed(
                        title=f"{product_name}",
                        description=(
                            f"**JAN:** `{jan}`\n"
                            f"**売価:** {price}円\n"
                            f"**画像:** {'あり' if has_images else '未設定'} / **説明文:** {'あり' if has_desc else '未設定'}\n"
                            f"**カテゴリID:** {' / '.join(cat_status)}"
                        ),
                        color=COLOR_PREVIEW,
                    )
                except (json.JSONDecodeError, KeyError):
                    embed = discord.Embed(
                        title=f"JAN: {jan}",
                        description="プレビュー情報を解析できませんでした。出品は続行可能です。",
                        color=COLOR_PREVIEW,
                    )
            else:
                embed = discord.Embed(
                    title=f"JAN: {jan}",
                    description="プレビュー取得失敗。出品は続行可能です。",
                    color=COLOR_PREVIEW,
                )
        else:
            if mall == "all":
                embed = discord.Embed(
                    title="ALL SHOP 全モール一括出品",
                    description=(
                        "**全6モール**に未出品のJANを一括出品します。\n"
                        "Amazon / Yahoo / Qoo10 / auPAY / Temu / メルカリ\n\n"
                        "データ不備のモールは自動スキップされます。"
                    ),
                    color=COLOR_PREVIEW,
                )
            else:
                embed = discord.Embed(
                    title=f"{mall.upper()} 一括出品",
                    description="SS-17「他モール出品」で未出品のJANを全て出品します。",
                    color=COLOR_PREVIEW,
                )

        mall_label = "全モール（Amazon/Yahoo/Qoo10/auPAY/Temu/メルカリ）" if mall == "all" else mall.upper()
        embed.set_footer(text=f"出品先: {mall_label}")

        # Step 3: 確認ボタン
        view = ListingConfirmView(user_id, mall, jan)
        await interaction.edit_original_response(embed=embed, view=view)

        await view.wait()

        if view.result == "cancel" or view.result is None:
            embed = discord.Embed(
                title="出品キャンセル",
                description=f"モール: {mall.upper()}",
                color=COLOR_CANCEL,
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        if view.result == "timeout":
            embed = discord.Embed(
                title="タイムアウト",
                description="5分以内にボタンが押されなかったため、キャンセルしました。",
                color=COLOR_CANCEL,
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        # Step 4: 出品実行
        dry_run = view.result == "dry_run"
        mode_label = "ドライラン" if dry_run else "出品"

        mall_display = "全モール" if mall == "all" else mall.upper()
        progress_embed = discord.Embed(
            title=f"{mode_label}実行中...",
            description=f"モール: {mall_display}\nしばらくお待ちください。",
            color=COLOR_WORKING,
        )
        await interaction.edit_original_response(embed=progress_embed, view=None)

        try:
            cmd = [
                "python3", PIPELINE_SCRIPT,
                "submit", "--mall", mall,
            ]
            if jan:
                cmd.extend(["--jan", jan])
            if dry_run:
                cmd.append("--dry-run")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timeout = SUBMIT_TIMEOUT_ALL if mall == "all" else SUBMIT_TIMEOUT
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="タイムアウト",
                description="出品処理に時間がかかりすぎました。手動で確認してください。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("shuppin submit failed")
            embed = discord.Embed(
                title="出品エラー",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 5: 結果表示
        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        try:
            result_data = json.loads(stdout_text)
        except (json.JSONDecodeError, ValueError):
            result_data = None

        if proc.returncode == 0:
            submit_info = result_data.get("submit", {}) if result_data else {}
            submit_stdout = submit_info.get("stdout", stdout_text)

            result_embed = discord.Embed(
                title=f"{mode_label}完了",
                description=f"モール: **{mall_display}**",
                color=COLOR_SUCCESS,
            )

            if submit_stdout:
                lines = submit_stdout.strip().split("\n")
                summary_lines = [ln for ln in lines[-15:] if ln.strip()]
                if summary_lines:
                    result_embed.add_field(
                        name="結果",
                        value=f"```\n{chr(10).join(summary_lines[-10:])}\n```",
                        inline=False,
                    )

            # スキップされたモールがあれば表示（listing.pyのJSON出力から取得）
            if result_data:
                skip_list = []
                try:
                    inner_stdout = result_data.get("submit", {}).get("stdout", "")
                    # listing.pyは最後の行にJSONを出力する
                    for line in reversed(inner_stdout.strip().split("\n")):
                        line = line.strip()
                        if line.startswith("{"):
                            inner = json.loads(line)
                            skip_list = inner.get("skipped", [])
                            break
                except (json.JSONDecodeError, ValueError, AttributeError):
                    pass
                if skip_list:
                    result_embed.add_field(
                        name="スキップ（データ不備）",
                        value=", ".join(skip_list),
                        inline=False,
                    )

            result_embed.set_footer(text="/shuppin mall:モール名 で次の出品へ")
            await interaction.edit_original_response(embed=result_embed)
        else:
            err_msg = ""
            if result_data:
                err_msg = result_data.get("error", "")
                submit_info = result_data.get("submit", {})
                if not err_msg and submit_info.get("stderr"):
                    err_msg = submit_info["stderr"]
            if not err_msg:
                err_msg = stderr_text[:800] if stderr_text else "不明なエラー"

            embed = discord.Embed(
                title="出品エラー",
                description=f"```\n{err_msg[:1000]}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)

        logger.info(
            "/shuppin by %s: mall=%s, jan=%s, result=%s",
            interaction.user.name, mall, jan or "all-unlisted",
            view.result,
        )
