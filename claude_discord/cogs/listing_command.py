"""スマホ出品コマンド Cog — /出品 JAN 原価 で全モール出品.

1商品ずつ完結フロー:
  /出品 4562188860587 1200
  → 商品情報+売価プレビュー（Embed）
  → [出品する] [やめる] ボタン
  → 各モール順次出品 → 完了通知

制約: 1人1商品ロック。前の処理が完了するまで次を受け付けない。
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
PREVIEW_TIMEOUT = 60  # 秒（SS読み込みがあるので長め）
SUBMIT_TIMEOUT = 300  # 秒（各モール出品）

# Embed カラー
COLOR_PREVIEW = 0x3498DB   # 青 - プレビュー
COLOR_SUCCESS = 0x2ECC71   # 緑 - 成功
COLOR_ERROR = 0xE74C3C     # 赤 - エラー
COLOR_CANCEL = 0x95A5A6    # グレー - キャンセル
COLOR_WORKING = 0xF39C12   # オレンジ - 処理中

# 1人1商品ロック: {user_id: jan}
_active_locks: dict[int, str] = {}


def _load_allowed_user_ids() -> set[int] | None:
    """SHUPPIN_ALLOWED_USER_IDS 環境変数からユーザーIDセットを取得.

    未設定 → DISCORD_OWNER_ID のみ許可。
    "*" → 全ユーザー許可。
    "id1,id2,..." → 指定ユーザーのみ許可。
    """
    raw = os.getenv("SHUPPIN_ALLOWED_USER_IDS", "")
    if raw.strip() == "*":
        return None  # 全員許可

    ids: set[int] = set()
    if raw.strip():
        for uid in raw.split(","):
            uid = uid.strip()
            if uid.isdigit():
                ids.add(int(uid))

    # 未設定の場合はオーナーIDだけ許可
    owner = os.getenv("DISCORD_OWNER_ID", "")
    if owner.strip().isdigit():
        ids.add(int(owner.strip()))

    return ids if ids else None


class ListingConfirmView(discord.ui.View):
    """出品確認ボタン（出品する / やめる）"""

    def __init__(self, jan: str, genka: float, user_id: int, preview_data: dict):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.jan = jan
        self.genka = genka
        self.user_id = user_id
        self.preview_data = preview_data
        self.result: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """ボタンを押せるのは元のユーザーのみ"""
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
    """スマホ出品 — JAN+原価で全モール出品."""

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
        description="スマホ出品（JAN+原価 → 全モール出品）",
    )
    @app_commands.describe(
        jan="JANコード（13桁）",
        genka="原価（税抜、円）",
    )
    async def shuppin(
        self,
        interaction: discord.Interaction,
        jan: str,
        genka: int,
    ) -> None:
        """JAN+原価を入力 → プレビュー → 承認 → 全モール出品."""
        user_id = interaction.user.id

        # ユーザー権限チェック
        if self._allowed_user_ids is not None and user_id not in self._allowed_user_ids:
            await interaction.response.send_message(
                "このコマンドの使用権限がありません。管理者に連絡してください。",
                ephemeral=True,
            )
            return

        jan = jan.strip()

        # JAN バリデーション
        if not jan.isdigit() or len(jan) not in (8, 13):
            await interaction.response.send_message(
                "JANコードは8桁または13桁の数字で入力してください。",
                ephemeral=True,
            )
            return

        if genka <= 0 or genka > 100000:
            await interaction.response.send_message(
                "原価は1〜100,000円の範囲で入力してください。",
                ephemeral=True,
            )
            return

        # 1商品ロックチェック
        if user_id in _active_locks:
            locked_jan = _active_locks[user_id]
            await interaction.response.send_message(
                f"前の出品処理（JAN: {locked_jan}）が進行中です。\n"
                "完了またはキャンセルしてから次の商品を入力してください。",
                ephemeral=True,
            )
            return

        # ロック取得
        _active_locks[user_id] = jan

        try:
            await self._process_listing(interaction, jan, genka, user_id)
        finally:
            # ロック解放
            _active_locks.pop(user_id, None)

    async def _process_listing(
        self,
        interaction: discord.Interaction,
        jan: str,
        genka: int,
        user_id: int,
    ) -> None:
        """出品フローのメイン処理"""

        # Step 1: 検索中の表示
        embed = discord.Embed(
            title="商品情報を取得中...",
            description=f"JAN: `{jan}` / 原価: {genka:,}円（税抜）",
            color=COLOR_WORKING,
        )
        await interaction.response.send_message(embed=embed)

        # Step 2: バックエンドでプレビュー取得
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", PIPELINE_SCRIPT,
                "preview", "--jan", jan, "--genka", str(genka),
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

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            embed = discord.Embed(
                title="エラー",
                description=f"```\n{err[:800]}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 3: JSON解析
        try:
            data = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            embed = discord.Embed(
                title="パースエラー",
                description="プレビュー結果の解析に失敗しました。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        if not data.get("ok"):
            embed = discord.Embed(
                title="エラー",
                description=data.get("error", "不明なエラー"),
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 4: プレビュー Embed 構築
        product = data.get("product", {})
        pricing = data.get("pricing", {})
        prices = pricing.get("prices", {})

        product_name = product.get("name") or f"JAN: {jan}"
        source = product.get("source", "")
        found = product.get("found", False)

        embed = discord.Embed(
            title=product_name,
            color=COLOR_PREVIEW,
        )

        # 基本情報
        basic_lines = [f"**JAN:** `{jan}`"]
        if product.get("maker"):
            basic_lines.append(f"**メーカー:** {product['maker']}")
        if product.get("brand"):
            basic_lines.append(f"**ブランド:** {product['brand']}")
        if product.get("dept"):
            basic_lines.append(f"**部門:** {product['dept']}")
        basic_lines.append(f"**データ元:** {source or '未登録'}")

        embed.add_field(
            name="基本情報",
            value="\n".join(basic_lines),
            inline=True,
        )

        # コスト
        cost_lines = [
            f"**原価(税抜):** {genka:,}円",
            f"**原価(税込):** {pricing.get('genka_zeikomi', 0):,}円",
            f"**送料:** {pricing.get('shipping', 0):,}円",
            f"**梱包費:** {pricing.get('packing', 0):,}円",
        ]
        embed.add_field(
            name="コスト",
            value="\n".join(cost_lines),
            inline=True,
        )

        # モール別売価
        price_lines = []
        for mall_name in ["楽天", "Amazon", "Yahoo", "Qoo10", "auPAY", "Temu"]:
            mp = prices.get(mall_name, {})
            if mp:
                p = mp.get("price", 0)
                rate = mp.get("profit_rate", 0)
                price_lines.append(
                    f"**{mall_name}:** {p:,}円 (利益率 {rate}%)"
                )

        embed.add_field(
            name="モール別売価（自動算出）",
            value="\n".join(price_lines) if price_lines else "計算エラー",
            inline=False,
        )

        # 注意事項
        warnings = []
        if not found:
            warnings.append("商品がマスタ未登録です。先に /shohin で確認してください。")
        if source == "SS-17":
            if not product.get("has_images"):
                warnings.append("画像が未設定です（白抜き画像生成が必要）")
            if not product.get("has_description"):
                warnings.append("商品説明文が未設定です")
        else:
            warnings.append("SS-17未登録。出品時に自動登録されます。")

        if warnings:
            embed.add_field(
                name="注意",
                value="\n".join(f"- {w}" for w in warnings),
                inline=False,
            )

        embed.set_footer(text="出品先: 楽天 / Amazon / Yahoo / Qoo10 / auPAY / Temu")

        # Step 5: ボタン表示
        view = ListingConfirmView(jan, genka, user_id, data)
        await interaction.edit_original_response(embed=embed, view=view)

        # Step 6: ボタン待機
        await view.wait()

        if view.result == "cancel" or view.result is None:
            embed = discord.Embed(
                title="出品キャンセル",
                description=f"{product_name}\nJAN: `{jan}`",
                color=COLOR_CANCEL,
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        if view.result == "timeout":
            embed = discord.Embed(
                title="タイムアウト",
                description="5分以内にボタンが押されなかったため、出品をキャンセルしました。",
                color=COLOR_CANCEL,
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        # Step 7: 出品実行
        dry_run = view.result == "dry_run"
        mode_label = "ドライラン" if dry_run else "出品"

        progress_embed = discord.Embed(
            title=f"{mode_label}実行中...",
            description=f"{product_name}\n各モールへ{mode_label}しています。しばらくお待ちください。",
            color=COLOR_WORKING,
        )
        await interaction.edit_original_response(embed=progress_embed, view=None)

        try:
            cmd = [
                "python3", PIPELINE_SCRIPT,
                "submit", "--jan", jan, "--genka", str(genka),
            ]
            if dry_run:
                cmd.append("--dry-run")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=SUBMIT_TIMEOUT
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

        # Step 8: 結果表示
        try:
            result_data = json.loads(stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            result_data = None

        if proc.returncode == 0 and result_data and result_data.get("ok"):
            ss17_info = result_data.get("ss17", {})
            submit_info = result_data.get("submit", {})

            result_embed = discord.Embed(
                title=f"{mode_label}完了",
                description=f"**{product_name}**\nJAN: `{jan}`",
                color=COLOR_SUCCESS,
            )

            # SS-17情報
            ss17_action = ss17_info.get("action", "")
            ss17_row = ss17_info.get("row", "")
            result_embed.add_field(
                name="SS-17",
                value=f"{'更新' if ss17_action == 'updated' else '新規追加'} (行{ss17_row})",
                inline=True,
            )

            # 出品結果のサマリ
            submit_stdout = submit_info.get("stdout", "")
            if submit_stdout:
                # 最後の数行だけ表示
                lines = submit_stdout.strip().split("\n")
                summary_lines = [l for l in lines[-15:] if l.strip()]
                if summary_lines:
                    result_embed.add_field(
                        name="出品結果",
                        value=f"```\n{chr(10).join(summary_lines[-10:])}\n```",
                        inline=False,
                    )

            result_embed.set_footer(text="次の商品をどうぞ！ /shuppin JAN 原価")
            await interaction.edit_original_response(embed=result_embed)
        else:
            err_msg = ""
            if result_data:
                err_msg = result_data.get("error", "")
            if not err_msg:
                err_msg = stderr.decode("utf-8", errors="replace")[:800] if stderr else "不明なエラー"

            embed = discord.Embed(
                title="出品エラー",
                description=f"```\n{err_msg}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)

        logger.info(
            "/shuppin by %s: jan=%s, genka=%d, result=%s",
            interaction.user.name, jan, genka,
            view.result,
        )
