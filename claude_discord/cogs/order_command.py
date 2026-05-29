"""手動発注コマンド Cog — /order JAN:cs で SS-07/SS-13 に発注登録.

2段階フロー:
  /order 4902397847281:3 4571104431404:5
  → プレビューEmbed（金額・仕入先・二重発注警告）
  → [発注する] [ドライラン] [JAN追加] [キャンセル] ボタン
  → 最低発注条件未達の場合は「発注する」無効化、JAN追加で条件充足可能
  → SS-07/SS-13書き込み + CSV生成 → 完了通知

制約: 1人1発注ロック。前の処理が完了するまで次を受け付けない。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# バックエンドスクリプト
ORDER_SCRIPT = "/home/ubuntu/ec-automation-system/scripts/manual_order.py"
PREVIEW_TIMEOUT = 60   # SS読み込みがあるので長め
EXECUTE_TIMEOUT = 120  # SS書き込み+CSV生成

# Embed カラー
COLOR_PREVIEW = 0x3498DB   # 青 - プレビュー
COLOR_SUCCESS = 0x2ECC71   # 緑 - 成功
COLOR_ERROR = 0xE74C3C     # 赤 - エラー
COLOR_CANCEL = 0x95A5A6    # グレー - キャンセル
COLOR_WORKING = 0xF39C12   # オレンジ - 処理中
COLOR_WARNING = 0xE67E22   # ダークオレンジ - 警告あり

# 1人1発注ロック: {user_id: "jans_str"}
_active_locks: dict[int, str] = {}

# 理由の選択肢
REASON_CHOICES = [
    app_commands.Choice(name="定期補充", value="restock"),
    app_commands.Choice(name="欠品補充", value="stockout"),
    app_commands.Choice(name="新規商品", value="new"),
    app_commands.Choice(name="セール準備", value="sale"),
]

# JAN追加→再プレビューの最大回数
MAX_ADD_ITERATIONS = 5


def _load_allowed_user_ids() -> set[int] | None:
    """ORDER_ALLOWED_USER_IDS 環境変数からユーザーIDセットを取得."""
    raw = os.getenv("ORDER_ALLOWED_USER_IDS", "")
    if raw.strip() == "*":
        return None  # 全員許可

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


class AddJanModal(discord.ui.Modal, title="追加JAN入力"):
    """最低発注条件を満たすために追加JANを入力するモーダル"""

    jans_input = discord.ui.TextInput(
        label="JAN:cs（スペースまたは改行区切り）",
        style=discord.TextStyle.paragraph,
        placeholder="4971618206053:1 4971618206251:2",
        required=True,
        max_length=500,
    )

    def __init__(self):
        super().__init__(timeout=120)
        self.added_jans: list[str] = []

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.jans_input.value.strip()
        items = raw.replace("\n", " ").split()
        valid_items = []
        errors = []
        for item in items:
            if ":" not in item:
                errors.append(f"`{item}`: JAN:cs形式で入力してください")
                continue
            jan, cs = item.split(":", 1)
            if not jan.isdigit():
                errors.append(f"`{item}`: JANが数値ではありません")
                continue
            if not cs.isdigit() or int(cs) <= 0:
                errors.append(f"`{item}`: cs数が不正です（1以上）")
                continue
            valid_items.append(item)

        if errors and not valid_items:
            await interaction.response.send_message(
                "\u274c 入力エラー:\n" + "\n".join(errors),
                ephemeral=True,
            )
            return

        if errors:
            await interaction.response.send_message(
                "\u26a0\ufe0f 一部エラー（有効なJANのみ追加します）:\n" + "\n".join(errors),
                ephemeral=True,
            )
        else:
            await interaction.response.defer()

        self.added_jans = valid_items


class OrderConfirmView(discord.ui.View):
    """発注確認ボタン（発注する / ドライラン / JAN追加 / キャンセル）"""

    def __init__(self, user_id: int, preview_path: str, min_conditions_met: bool = True):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.user_id = user_id
        self.preview_path = preview_path
        self.result: str | None = None
        self.added_jans: list[str] = []

        if not min_conditions_met:
            # 「発注する」ボタンを無効化
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label == "\u767a\u6ce8\u3059\u308b":
                    item.disabled = True
                    break
            # 「JAN追加」ボタンを動的に追加
            add_btn = discord.ui.Button(
                label="JAN\u8ffd\u52a0",
                style=discord.ButtonStyle.primary,
                emoji="\u2795",
            )
            add_btn.callback = self._on_add_jan
            self.add_item(add_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このボタンは操作できません。", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="\u767a\u6ce8\u3059\u308b", style=discord.ButtonStyle.success, emoji="\u2705")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "confirm"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="\u30c9\u30e9\u30a4\u30e9\u30f3", style=discord.ButtonStyle.secondary, emoji="\U0001F9EA")
    async def dry_run(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "dry_run"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="\u30ad\u30e3\u30f3\u30bb\u30eb", style=discord.ButtonStyle.danger, emoji="\u274C")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "cancel"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _on_add_jan(self, interaction: discord.Interaction):
        """JAN追加ボタン → モーダルを開き、入力されたJANで再プレビュー"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このボタンは操作できません。", ephemeral=True
            )
            return
        modal = AddJanModal()
        await interaction.response.send_modal(modal)
        timed_out = await modal.wait()
        if timed_out or not modal.added_jans:
            return
        self.added_jans = modal.added_jans
        self.result = "add_jans"
        for item in self.children:
            item.disabled = True
        self.stop()

    async def on_timeout(self):
        self.result = "timeout"
        self.stop()


def _build_preview_embed(preview: dict, user_display_name: str = "") -> discord.Embed:
    """プレビューJSONからEmbed を構築"""
    orders = preview.get("orders", [])
    errors = preview.get("errors", [])
    warnings = preview.get("warnings", [])
    supplier_summary = preview.get("supplierSummary", {})
    total_amount = preview.get("totalAmount", 0)
    order_date = preview.get("orderDate", "")
    reason = preview.get("reason", "")

    has_warnings = len(warnings) > 0
    color = COLOR_WARNING if has_warnings else COLOR_PREVIEW

    embed = discord.Embed(
        title=f"\u624b\u52d5\u767a\u6ce8\u30d7\u30ec\u30d3\u30e5\u30fc  {order_date}",
        color=color,
    )

    if user_display_name:
        embed.description = f"\u767a\u6ce8\u8005: **{user_display_name}**"

    # 発注明細
    if orders:
        lines = []
        for i, o in enumerate(orders):
            name = o["productName"][:22]
            dup = " **[\u4e8c\u91cd]**" if o.get("isDuplicate") else ""
            wh = "Y" if o.get("warehouse") == "\u30e4\u30de\u30c8\u5009\u5eab" else "T"
            cost = o.get("cost", 0)
            stock = o.get("stock", 0)
            lines.append(
                f"`{o['jan']}` {name}\n"
                f"  {wh} | @\\{cost:,.0f} | \u5728\u5eab{stock} | "
                f"{o['orderCs']}cs({o['orderQty']}\u500b) | "
                f"\\{o['amount']:,.0f} | {o['expectedDate']}{dup}"
            )
            if i >= 14:
                lines.append(f"... \u4ed6 {len(orders) - 15}\u4ef6")
                break

        # Embed field は 1024文字制限 — 長い場合は分割
        detail_text = "\n".join(lines)
        if len(detail_text) > 1024:
            detail_text = detail_text[:1020] + "..."
        embed.add_field(name="\u767a\u6ce8\u660e\u7d30", value=detail_text, inline=False)

    # エラー
    if errors:
        err_text = "\n".join(f"- {e}" for e in errors[:5])
        if len(errors) > 5:
            err_text += f"\n... \u4ed6 {len(errors) - 5}\u4ef6"
        embed.add_field(name="\u30a8\u30e9\u30fc", value=err_text, inline=False)

    # 警告
    if warnings:
        warn_text = "\n".join(w for w in warnings[:5])
        if len(warnings) > 5:
            warn_text += f"\n... \u4ed6 {len(warnings) - 5}\u4ef6"
        embed.add_field(name="\u8b66\u544a", value=warn_text, inline=False)

    # 仕入先別集計
    if supplier_summary:
        summary_lines = []
        for supplier, info in supplier_summary.items():
            summary_lines.append(
                f"**{supplier}**: {info['count']}\u54c1 {info['totalCs']}cs "
                f"\\{info['totalAmount']:,.0f}"
            )
        embed.add_field(
            name="\u4ed5\u5165\u5148\u5225\u96c6\u8a08",
            value="\n".join(summary_lines),
            inline=True,
        )

    # 最低発注条件（仕入先+メーカー別に集約して表示）
    if orders:
        # 仕入先+メーカーごとのcs・金額を集計
        sm_totals: dict[str, dict] = {}
        for o in orders:
            key = f"{o.get('supplier', '')}___{o.get('maker', '')}"
            if key not in sm_totals:
                sm_totals[key] = {
                    "supplier": o.get("supplier", ""),
                    "maker": o.get("maker", ""),
                    "totalCs": 0,
                    "totalAmount": 0,
                    "minCs": o.get("minCs", 0),
                    "minAmount": o.get("minAmount", 0),
                }
            sm_totals[key]["totalCs"] += o.get("orderCs", 0)
            sm_totals[key]["totalAmount"] += o.get("amount", 0)

        cond_lines = []
        for info in sm_totals.values():
            min_cs = info["minCs"]
            min_amt = info["minAmount"]
            if min_cs <= 0 and min_amt <= 0:
                continue
            label = info["supplier"]
            if info["maker"]:
                label += f"/{info['maker']}"
            parts = []
            if min_cs > 0:
                ok = "\u2705" if info["totalCs"] >= min_cs else "\u274C"
                parts.append(f"\u6700\u5c0f{min_cs}cs{ok}")
            if min_amt > 0:
                ok = "\u2705" if info["totalAmount"] >= min_amt else "\u274C"
                parts.append(f"\u6700\u4f4e\\{min_amt:,.0f}{ok}")
            cond_lines.append(f"**{label}**: {' / '.join(parts)}")

        if cond_lines:
            cond_text = "\n".join(cond_lines)
            if len(cond_text) > 1024:
                cond_text = cond_text[:1020] + "..."
            embed.add_field(
                name="\u6700\u4f4e\u767a\u6ce8\u6761\u4ef6",
                value=cond_text,
                inline=True,
            )

    # 追加発注候補（最低発注条件 未達メーカーの補充候補）
    candidates = preview.get("candidates", {})
    if candidates:
        for key, cands in candidates.items():
            if not cands:
                continue
            parts = key.split("___", 1)
            label = f"{parts[0]}/{parts[1]}" if len(parts) > 1 and parts[1] else parts[0]
            cand_lines = []
            for c in cands[:10]:
                name = c.get("productName", "")[:20]
                stock = c.get("stock", 0)
                rp = c.get("reorderPoint", 0)
                diff = c.get("stockMinusRp", 0)
                cand_lines.append(
                    f"`{c['jan']}` {name}\n"
                    f"  \u5728\u5eab{stock} / \u767a\u6ce8\u70b9{rp} / \u5dee{diff:+d}"
                )
            if len(cands) > 10:
                cand_lines.append(f"... \u4ed6 {len(cands) - 10}\u4ef6")
            cand_text = "\n".join(cand_lines)
            if len(cand_text) > 1024:
                cand_text = cand_text[:1020] + "..."
            embed.add_field(
                name=f"\u8ffd\u52a0\u767a\u6ce8\u5019\u88dc {label}",
                value=cand_text,
                inline=False,
            )

    # フッター: 合計 + 理由
    footer_parts = [f"\u5408\u8a08: {len(orders)}\u54c1  \\{total_amount:,.0f}"]
    if reason:
        footer_parts.append(f"\u7406\u7531: {reason}")
    # 条件未達の場合はフッターに案内
    if not preview.get("minConditionsMet", True):
        footer_parts.append("\u26a0\ufe0f \u6700\u4f4e\u767a\u6ce8\u6761\u4ef6\u672a\u9054\u306e\u305f\u3081\u300cJAN\u8ffd\u52a0\u300d\u3067\u5546\u54c1\u3092\u8ffd\u52a0\u3057\u3066\u304f\u3060\u3055\u3044")
    embed.set_footer(text=" | ".join(footer_parts))

    return embed


def _build_result_embed(result: dict, dry_run: bool, email_result: dict | None = None) -> discord.Embed:
    """実行結果JSONからEmbed を構築"""
    status = result.get("status", "")
    order_ids = result.get("orderIds", [])
    total_items = result.get("totalItems", 0)
    total_amount = result.get("totalAmount", 0)
    csv_files = result.get("csvFiles", [])
    supplier_summary = result.get("supplierSummary", {})
    order_date = result.get("orderDate", "")

    mode = "\u30c9\u30e9\u30a4\u30e9\u30f3\u5b8c\u4e86" if dry_run else "\u767a\u6ce8\u5b8c\u4e86"
    color = COLOR_SUCCESS if not dry_run else COLOR_PREVIEW

    embed = discord.Embed(
        title=f"{mode}  {order_date}",
        color=color,
    )

    # 発注ID
    if order_ids:
        id_first = order_ids[0]
        id_last = order_ids[-1] if len(order_ids) > 1 else ""
        id_text = f"`{id_first}`"
        if id_last:
            id_text += f" \u301c `{id_last}`"
        embed.add_field(name="\u767a\u6ce8ID", value=id_text, inline=False)

    # 書き込み先
    if not dry_run:
        write_targets = [
            "SS-07 \u767a\u6ce8\u6e08\u672a\u5230\u7740",
            "SS-07 \u767a\u6ce8\u5c65\u6b74",
            "SS-07 \u30de\u30b9\u30bf(O/P/Q\u5217)",
            "SS-13 \u5165\u5eab\u5f85\u3061",
        ]
        embed.add_field(
            name="\u66f8\u304d\u8fbc\u307f\u5148",
            value="\n".join(f"- {t}" for t in write_targets),
            inline=True,
        )
    else:
        embed.add_field(
            name="\u66f8\u304d\u8fbc\u307f\u5148",
            value="(\u30c9\u30e9\u30a4\u30e9\u30f3\u306e\u305f\u3081\u66f8\u304d\u8fbc\u307f\u306a\u3057)",
            inline=True,
        )

    # CSV
    if csv_files:
        csv_lines = [f"`{Path(f).name}`" for f in csv_files]
        embed.add_field(
            name=f"CSV ({len(csv_files)}\u4ef6)",
            value="\n".join(csv_lines),
            inline=True,
        )

    # 仕入先別
    if supplier_summary:
        summary_lines = []
        for supplier, info in supplier_summary.items():
            summary_lines.append(
                f"**{supplier}**: {info['count']}\u54c1 \\{info['totalAmount']:,.0f}"
            )
        embed.add_field(
            name="\u4ed5\u5165\u5148\u5225",
            value="\n".join(summary_lines),
            inline=False,
        )

    # メール送信結果
    if not dry_run and email_result is not None:
        if "error" in email_result:
            embed.add_field(
                name="\u30e1\u30fc\u30eb\u9001\u4fe1",
                value=f"\u9001\u4fe1\u5931\u6557: {email_result['error'][:200]}",
                inline=False,
            )
        else:
            sent_count = email_result.get("sentCount", 0)
            sent_list = email_result.get("sent", [])
            mail_lines = [f"\u9001\u4fe1\u6210\u529f: {sent_count}\u4ef6"]
            for s in sent_list[:5]:
                wh = f" [{s.get('warehouse', '')}]" if s.get('warehouse') else ""
                mail_lines.append(
                    f"  {s.get('supplier', '?')}{wh} \u2192 {s.get('email', '?')}"
                )
            embed.add_field(
                name="\u30e1\u30fc\u30eb\u9001\u4fe1",
                value="\n".join(mail_lines),
                inline=False,
            )
    elif not dry_run and email_result is None:
        embed.add_field(
            name="\u30e1\u30fc\u30eb\u9001\u4fe1",
            value="GAS_MANUAL_ORDER_URL \u672a\u8a2d\u5b9a\u306e\u305f\u3081\u30b9\u30ad\u30c3\u30d7\nSS-07 \u30e1\u30cb\u30e5\u30fc\u300c\u81ea\u52d5\u767a\u6ce8\u30e1\u30cb\u30e5\u30fc\u300d\u2192\u300c\u624b\u52d5\u767a\u6ce8\u30e1\u30fc\u30eb\u9001\u4fe1\u300d\u3067\u624b\u52d5\u9001\u4fe1",
            inline=False,
        )

    embed.set_footer(
        text=f"\u5408\u8a08: {total_items}\u54c1  \\{total_amount:,.0f}"
    )

    return embed


def _dedup_jan_items(jan_items: list[str]) -> list[str]:
    """同じJANが複数ある場合にcs数を合算して重複排除"""
    jan_cs: dict[str, int] = {}
    for item in jan_items:
        jan, cs = item.split(":", 1)
        jan_cs[jan] = jan_cs.get(jan, 0) + int(cs)
    return [f"{jan}:{cs}" for jan, cs in jan_cs.items()]


class OrderCommandCog(commands.Cog):
    """手動発注 — JAN:cs で SS-07/SS-13 に発注登録."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._allowed_user_ids = _load_allowed_user_ids()
        if self._allowed_user_ids is not None:
            logger.info(
                "OrderCommandCog: allowed users = %s",
                ", ".join(str(uid) for uid in self._allowed_user_ids),
            )
        else:
            logger.info("OrderCommandCog: all users allowed")

    @app_commands.command(
        name="order",
        description="\u624b\u52d5\u767a\u6ce8\uff08JAN:cs \u2192 \u30d7\u30ec\u30d3\u30e5\u30fc \u2192 \u78ba\u8a8d \u2192 SS-07/SS-13\u66f8\u304d\u8fbc\u307f\uff09",
    )
    @app_commands.describe(
        jans="JAN:cs\u5f62\u5f0f\uff08\u8907\u6570\u306f\u30b9\u30da\u30fc\u30b9\u533a\u5207\u308a\uff09\u4f8b: 4902397847281:3 4571104431404:5",
        reason="\u767a\u6ce8\u7406\u7531\uff08\u30c7\u30d5\u30a9\u30eb\u30c8: \u5b9a\u671f\u88dc\u5145\uff09",
    )
    @app_commands.choices(reason=REASON_CHOICES)
    async def order(
        self,
        interaction: discord.Interaction,
        jans: str,
        reason: app_commands.Choice[str] | None = None,
    ) -> None:
        """JAN:csを入力 → プレビュー → 承認 → 発注確定."""
        user_id = interaction.user.id

        # ユーザー権限チェック
        if self._allowed_user_ids is not None and user_id not in self._allowed_user_ids:
            await interaction.response.send_message(
                "\u3053\u306e\u30b3\u30de\u30f3\u30c9\u306e\u4f7f\u7528\u6a29\u9650\u304c\u3042\u308a\u307e\u305b\u3093\u3002\u7ba1\u7406\u8005\u306b\u9023\u7d61\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
                ephemeral=True,
            )
            return

        jans = jans.strip()
        if not jans:
            await interaction.response.send_message(
                "JAN:cs\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002\u4f8b: `4902397847281:3`",
                ephemeral=True,
            )
            return

        # JAN:cs 形式のバリデーション
        jan_items = []
        for item in jans.split():
            # フラグ混入を除去（--reason:欠品 のようなものを弾く）
            if item.startswith("-"):
                continue
            if ":" not in item:
                await interaction.response.send_message(
                    f"\u4e0d\u6b63\u306a\u5f62\u5f0f: `{item}`\nJAN:cs \u306e\u5f62\u5f0f\u3067\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\uff08\u4f8b: `4902397847281:3`\uff09",
                    ephemeral=True,
                )
                return
            jan_part, cs_part = item.split(":", 1)
            if not jan_part.isdigit():
                await interaction.response.send_message(
                    f"JAN\u304c\u6570\u5024\u3067\u306f\u3042\u308a\u307e\u305b\u3093: `{item}`",
                    ephemeral=True,
                )
                return
            if not cs_part.isdigit() or int(cs_part) <= 0:
                await interaction.response.send_message(
                    f"cs\u6570\u304c\u4e0d\u6b63\u3067\u3059: `{item}`\uff081\u4ee5\u4e0a\u306e\u6570\u5024\u3092\u6307\u5b9a\uff09",
                    ephemeral=True,
                )
                return
            jan_items.append(item)

        if not jan_items:
            await interaction.response.send_message(
                "\u6709\u52b9\u306aJAN:cs\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u4f8b: `4902397847281:3`",
                ephemeral=True,
            )
            return

        # 1人1発注ロック
        if user_id in _active_locks:
            locked = _active_locks[user_id]
            await interaction.response.send_message(
                f"\u524d\u306e\u767a\u6ce8\u51e6\u7406\u304c\u9032\u884c\u4e2d\u3067\u3059: `{locked}`\n"
                "\u5b8c\u4e86\u307e\u305f\u306f\u30ad\u30e3\u30f3\u30bb\u30eb\u3057\u3066\u304b\u3089\u6b21\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
                ephemeral=True,
            )
            return

        _active_locks[user_id] = jans

        try:
            await self._process_order(interaction, jan_items, reason, user_id)
        finally:
            _active_locks.pop(user_id, None)

    async def _process_order(
        self,
        interaction: discord.Interaction,
        jan_items: list[str],
        reason: app_commands.Choice[str] | None,
        user_id: int,
    ) -> None:
        """発注フローのメイン処理（JAN追加→再プレビューのループ対応）"""
        # reason がChoiceオブジェクトか生の文字列かを安全に処理
        if reason is None:
            reason_value = "restock"
            reason_label = "\u5b9a\u671f\u88dc\u5145"
        elif hasattr(reason, "value"):
            reason_value = reason.value
            reason_label = reason.name
        else:
            reason_value = str(reason)
            reason_label = str(reason)

        user_display_name = interaction.user.display_name

        # Step 1: 処理中表示
        embed = discord.Embed(
            title="\u767a\u6ce8\u5185\u5bb9\u3092\u691c\u8a3c\u4e2d...",
            description=f"\u5bfe\u8c61: {len(jan_items)}\u54c1\n\u7406\u7531: {reason_label}",
            color=COLOR_WORKING,
        )
        await interaction.response.send_message(embed=embed)

        # Preview → ボタン → (JAN追加 → 再Preview) のループ
        preview_path = None
        view = None
        iteration = 0

        while iteration < MAX_ADD_ITERATIONS:
            iteration += 1

            # 重複JAN統合
            jan_items = _dedup_jan_items(jan_items)

            # Run preview
            cmd = [
                "python3", ORDER_SCRIPT,
                "preview",
                *jan_items,
                "--reason", reason_value,
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=PREVIEW_TIMEOUT
                )
            except asyncio.TimeoutError:
                embed = discord.Embed(
                    title="\u30bf\u30a4\u30e0\u30a2\u30a6\u30c8",
                    description="\u30d7\u30ec\u30d3\u30e5\u30fc\u53d6\u5f97\u306b\u6642\u9593\u304c\u304b\u304b\u308a\u3059\u304e\u307e\u3057\u305f\u3002",
                    color=COLOR_ERROR,
                )
                await interaction.edit_original_response(embed=embed, view=None)
                return
            except Exception as e:
                logger.exception("order preview failed")
                embed = discord.Embed(
                    title="\u30a8\u30e9\u30fc",
                    description=f"\u30d7\u30ec\u30d3\u30e5\u30fc\u53d6\u5f97\u306b\u5931\u6557: {e}",
                    color=COLOR_ERROR,
                )
                await interaction.edit_original_response(embed=embed, view=None)
                return

            # プレビューJSON読み取り
            preview_path = stdout.decode("utf-8", errors="replace").strip()
            if not preview_path or not Path(preview_path).exists():
                err = stderr.decode("utf-8", errors="replace").strip()
                embed = discord.Embed(
                    title="\u30d7\u30ec\u30d3\u30e5\u30fc\u30a8\u30e9\u30fc",
                    description=f"```\n{err[:800]}\n```" if err else "\u30d7\u30ec\u30d3\u30e5\u30fc\u30d5\u30a1\u30a4\u30eb\u304c\u751f\u6210\u3055\u308c\u307e\u305b\u3093\u3067\u3057\u305f\u3002",
                    color=COLOR_ERROR,
                )
                await interaction.edit_original_response(embed=embed, view=None)
                return

            try:
                preview_data = json.loads(
                    Path(preview_path).read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as e:
                embed = discord.Embed(
                    title="\u30d1\u30fc\u30b9\u30a8\u30e9\u30fc",
                    description=f"\u30d7\u30ec\u30d3\u30e5\u30fc\u7d50\u679c\u306e\u89e3\u6790\u306b\u5931\u6557: {e}",
                    color=COLOR_ERROR,
                )
                await interaction.edit_original_response(embed=embed, view=None)
                return

            # 有効な発注がなければエラーのみ表示
            orders = preview_data.get("orders", [])
            errors = preview_data.get("errors", [])

            if not orders:
                embed = discord.Embed(
                    title="\u767a\u6ce8\u5bfe\u8c61\u306a\u3057",
                    description="\u6709\u52b9\u306a\u767a\u6ce8\u5bfe\u8c61\u304c\u3042\u308a\u307e\u305b\u3093\u3067\u3057\u305f\u3002",
                    color=COLOR_ERROR,
                )
                if errors:
                    embed.add_field(
                        name="\u30a8\u30e9\u30fc",
                        value="\n".join(f"- {e}" for e in errors[:10]),
                        inline=False,
                    )
                await interaction.edit_original_response(embed=embed, view=None)
                return

            # プレビュー Embed + ボタン表示
            min_conditions_met = preview_data.get("minConditionsMet", True)
            preview_embed = _build_preview_embed(preview_data, user_display_name)
            view = OrderConfirmView(user_id, preview_path, min_conditions_met=min_conditions_met)
            await interaction.edit_original_response(embed=preview_embed, view=view)

            # ボタン待機
            await view.wait()

            if view.result == "add_jans" and view.added_jans:
                # JAN追加 → 再プレビュー
                jan_items = jan_items + view.added_jans
                loading = discord.Embed(
                    title="\u767a\u6ce8\u5185\u5bb9\u3092\u518d\u691c\u8a3c\u4e2d...",
                    description=f"\u5bfe\u8c61: {len(jan_items)}\u54c1\uff08{len(view.added_jans)}\u54c1\u8ffd\u52a0\uff09\n\u7406\u7531: {reason_label}",
                    color=COLOR_WORKING,
                )
                await interaction.edit_original_response(embed=loading, view=None)
                continue

            if view.result == "cancel" or view.result is None:
                embed = discord.Embed(
                    title="\u767a\u6ce8\u30ad\u30e3\u30f3\u30bb\u30eb",
                    description=f"{len(orders)}\u54c1\u306e\u767a\u6ce8\u3092\u30ad\u30e3\u30f3\u30bb\u30eb\u3057\u307e\u3057\u305f\u3002",
                    color=COLOR_CANCEL,
                )
                await interaction.edit_original_response(embed=embed, view=None)
                return

            if view.result == "timeout":
                embed = discord.Embed(
                    title="\u30bf\u30a4\u30e0\u30a2\u30a6\u30c8",
                    description="5\u5206\u4ee5\u5185\u306b\u30dc\u30bf\u30f3\u304c\u62bc\u3055\u308c\u306a\u304b\u3063\u305f\u305f\u3081\u3001\u767a\u6ce8\u3092\u30ad\u30e3\u30f3\u30bb\u30eb\u3057\u307e\u3057\u305f\u3002",
                    color=COLOR_CANCEL,
                )
                await interaction.edit_original_response(embed=embed, view=None)
                return

            # confirm or dry_run → ループ脱出
            break

        # Step 7: 発注実行
        dry_run = view.result == "dry_run"
        mode_label = "\u30c9\u30e9\u30a4\u30e9\u30f3" if dry_run else "\u767a\u6ce8"

        progress_embed = discord.Embed(
            title=f"{mode_label}\u5b9f\u884c\u4e2d...",
            description=f"{len(orders)}\u54c1\u3092\u51e6\u7406\u3057\u3066\u3044\u307e\u3059\u3002\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002",
            color=COLOR_WORKING,
        )
        await interaction.edit_original_response(embed=progress_embed, view=None)

        # execute 実行（--user でDiscord表示名を渡す）
        exec_cmd = [
            "python3", ORDER_SCRIPT,
            "execute", preview_path,
            "--user", user_display_name,
        ]
        if dry_run:
            exec_cmd.append("--dry-run")

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=EXECUTE_TIMEOUT
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="\u30bf\u30a4\u30e0\u30a2\u30a6\u30c8",
                description="\u767a\u6ce8\u51e6\u7406\u306b\u6642\u9593\u304c\u304b\u304b\u308a\u3059\u304e\u307e\u3057\u305f\u3002\u624b\u52d5\u3067\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("order execute failed")
            embed = discord.Embed(
                title="\u767a\u6ce8\u30a8\u30e9\u30fc",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 8: 結果表示
        result_path = stdout.decode("utf-8", errors="replace").strip()
        result_data = None
        if result_path and Path(result_path).exists():
            try:
                result_data = json.loads(
                    Path(result_path).read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                pass

        if proc.returncode != 0 or not result_data:
            err_msg = stderr.decode("utf-8", errors="replace")[:800] if stderr else "\u4e0d\u660e\u306a\u30a8\u30e9\u30fc"
            embed = discord.Embed(
                title="\u767a\u6ce8\u30a8\u30e9\u30fc",
                description=f"```\n{err_msg}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 9: メール送信（本番のみ。GAS_MANUAL_ORDER_URL が設定されている場合）
        email_result = None
        if not dry_run:
            gas_url = os.environ.get("GAS_MANUAL_ORDER_URL", "")
            if gas_url:
                progress_embed = discord.Embed(
                    title="\u30e1\u30fc\u30eb\u9001\u4fe1\u4e2d...",
                    description="\u4ed5\u5165\u5148\u306b\u30e1\u30fc\u30eb\u3092\u9001\u4fe1\u3057\u3066\u3044\u307e\u3059\u3002",
                    color=COLOR_WORKING,
                )
                await interaction.edit_original_response(embed=progress_embed)

                try:
                    email_proc = await asyncio.create_subprocess_exec(
                        "python3", ORDER_SCRIPT, "send-emails",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    email_stdout, email_stderr = await asyncio.wait_for(
                        email_proc.communicate(), timeout=EXECUTE_TIMEOUT
                    )
                    if email_proc.returncode == 0:
                        email_result_path = email_stdout.decode("utf-8", errors="replace").strip()
                        if email_result_path and Path(email_result_path).exists():
                            email_result = json.loads(
                                Path(email_result_path).read_text(encoding="utf-8")
                            )
                except Exception as e:
                    logger.warning("order send-emails failed: %s", e)
                    email_result = {"error": str(e)}

        # Step 10: 最終結果 Embed
        result_embed = _build_result_embed(result_data, dry_run, email_result)
        await interaction.edit_original_response(embed=result_embed)

        logger.info(
            "/order by %s: items=%s, reason=%s, result=%s, dry_run=%s",
            interaction.user.name,
            " ".join(jan_items),
            reason_value,
            view.result,
            dry_run,
        )
