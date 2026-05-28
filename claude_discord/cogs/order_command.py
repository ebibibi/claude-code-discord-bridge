"""手動発注コマンド Cog — /order JAN:cs で SS-07/SS-13 に発注登録.

2段階フロー:
  /order 4902397847281:3 4571104431404:5
  → プレビューEmbed（金額・仕入先・二重発注警告）
  → [発注する] [キャンセル] ボタン
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


class OrderConfirmView(discord.ui.View):
    """発注確認ボタン（発注する / ドライラン / キャンセル）"""

    def __init__(self, user_id: int, preview_path: str):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.user_id = user_id
        self.preview_path = preview_path
        self.result: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このボタンは操作できません。", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="発注する", style=discord.ButtonStyle.success, emoji="\u2705")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "confirm"
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

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.danger, emoji="\u274C")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = "cancel"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
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
        title=f"手動発注プレビュー  {order_date}",
        color=color,
    )

    if user_display_name:
        embed.description = f"発注者: **{user_display_name}**"

    # 発注明細
    if orders:
        lines = []
        for i, o in enumerate(orders):
            name = o["productName"][:22]
            dup = " **[二重]**" if o.get("isDuplicate") else ""
            wh = "Y" if o.get("warehouse") == "ヤマト倉庫" else "T"
            cost = o.get("cost", 0)
            stock = o.get("stock", 0)
            lines.append(
                f"`{o['jan']}` {name}\n"
                f"  {wh} | @\\{cost:,.0f} | 在庫{stock} | "
                f"{o['orderCs']}cs({o['orderQty']}個) | "
                f"\\{o['amount']:,.0f} | {o['expectedDate']}{dup}"
            )
            if i >= 14:
                lines.append(f"... 他 {len(orders) - 15}件")
                break

        # Embed field は 1024文字制限 — 長い場合は分割
        detail_text = "\n".join(lines)
        if len(detail_text) > 1024:
            detail_text = detail_text[:1020] + "..."
        embed.add_field(name="発注明細", value=detail_text, inline=False)

    # エラー
    if errors:
        err_text = "\n".join(f"- {e}" for e in errors[:5])
        if len(errors) > 5:
            err_text += f"\n... 他 {len(errors) - 5}件"
        embed.add_field(name="エラー", value=err_text, inline=False)

    # 警告
    if warnings:
        warn_text = "\n".join(w for w in warnings[:5])
        if len(warnings) > 5:
            warn_text += f"\n... 他 {len(warnings) - 5}件"
        embed.add_field(name="警告", value=warn_text, inline=False)

    # 仕入先別集計
    if supplier_summary:
        summary_lines = []
        for supplier, info in supplier_summary.items():
            summary_lines.append(
                f"**{supplier}**: {info['count']}品 {info['totalCs']}cs "
                f"\\{info['totalAmount']:,.0f}"
            )
        embed.add_field(
            name="仕入先別集計",
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
                parts.append(f"最小{min_cs}cs{ok}")
            if min_amt > 0:
                ok = "\u2705" if info["totalAmount"] >= min_amt else "\u274C"
                parts.append(f"最低\\{min_amt:,.0f}{ok}")
            cond_lines.append(f"**{label}**: {' / '.join(parts)}")

        if cond_lines:
            cond_text = "\n".join(cond_lines)
            if len(cond_text) > 1024:
                cond_text = cond_text[:1020] + "..."
            embed.add_field(
                name="最低発注条件",
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
                    f"  在庫{stock} / 発注点{rp} / 差{diff:+d}"
                )
            if len(cands) > 10:
                cand_lines.append(f"... 他 {len(cands) - 10}件")
            cand_text = "\n".join(cand_lines)
            if len(cand_text) > 1024:
                cand_text = cand_text[:1020] + "..."
            embed.add_field(
                name=f"追加発注候補 {label}",
                value=cand_text,
                inline=False,
            )

    # フッター: 合計 + 理由
    footer_parts = [f"合計: {len(orders)}品  \\{total_amount:,.0f}"]
    if reason:
        footer_parts.append(f"理由: {reason}")
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

    mode = "ドライラン完了" if dry_run else "発注完了"
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
            id_text += f" 〜 `{id_last}`"
        embed.add_field(name="発注ID", value=id_text, inline=False)

    # 書き込み先
    if not dry_run:
        write_targets = [
            "SS-07 発注済未到着",
            "SS-07 発注履歴",
            "SS-07 マスタ(O/P/Q列)",
            "SS-13 入庫待ち",
        ]
        embed.add_field(
            name="書き込み先",
            value="\n".join(f"- {t}" for t in write_targets),
            inline=True,
        )
    else:
        embed.add_field(
            name="書き込み先",
            value="(ドライランのため書き込みなし)",
            inline=True,
        )

    # CSV
    if csv_files:
        csv_lines = [f"`{Path(f).name}`" for f in csv_files]
        embed.add_field(
            name=f"CSV ({len(csv_files)}件)",
            value="\n".join(csv_lines),
            inline=True,
        )

    # 仕入先別
    if supplier_summary:
        summary_lines = []
        for supplier, info in supplier_summary.items():
            summary_lines.append(
                f"**{supplier}**: {info['count']}品 \\{info['totalAmount']:,.0f}"
            )
        embed.add_field(
            name="仕入先別",
            value="\n".join(summary_lines),
            inline=False,
        )

    # メール送信結果
    if not dry_run and email_result is not None:
        if "error" in email_result:
            embed.add_field(
                name="メール送信",
                value=f"送信失敗: {email_result['error'][:200]}",
                inline=False,
            )
        else:
            sent_count = email_result.get("sentCount", 0)
            sent_list = email_result.get("sent", [])
            mail_lines = [f"送信成功: {sent_count}件"]
            for s in sent_list[:5]:
                wh = f" [{s.get('warehouse', '')}]" if s.get('warehouse') else ""
                mail_lines.append(
                    f"  {s.get('supplier', '?')}{wh} → {s.get('email', '?')}"
                )
            embed.add_field(
                name="メール送信",
                value="\n".join(mail_lines),
                inline=False,
            )
    elif not dry_run and email_result is None:
        embed.add_field(
            name="メール送信",
            value="GAS_MANUAL_ORDER_URL 未設定のためスキップ\nSS-07 メニュー「自動発注メニュー」→「手動発注メール送信」で手動送信",
            inline=False,
        )

    embed.set_footer(
        text=f"合計: {total_items}品  \\{total_amount:,.0f}"
    )

    return embed


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
        description="手動発注（JAN:cs → プレビュー → 確認 → SS-07/SS-13書き込み）",
    )
    @app_commands.describe(
        jans="JAN:cs形式（複数はスペース区切り）例: 4902397847281:3 4571104431404:5",
        reason="発注理由（デフォルト: 定期補充）",
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
                "このコマンドの使用権限がありません。管理者に連絡してください。",
                ephemeral=True,
            )
            return

        jans = jans.strip()
        if not jans:
            await interaction.response.send_message(
                "JAN:csを入力してください。例: `4902397847281:3`",
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
                    f"不正な形式: `{item}`\nJAN:cs の形式で入力してください（例: `4902397847281:3`）",
                    ephemeral=True,
                )
                return
            jan_part, cs_part = item.split(":", 1)
            if not jan_part.isdigit():
                await interaction.response.send_message(
                    f"JANが数値ではありません: `{item}`",
                    ephemeral=True,
                )
                return
            if not cs_part.isdigit() or int(cs_part) <= 0:
                await interaction.response.send_message(
                    f"cs数が不正です: `{item}`（1以上の数値を指定）",
                    ephemeral=True,
                )
                return
            jan_items.append(item)

        if not jan_items:
            await interaction.response.send_message(
                "有効なJAN:csが見つかりませんでした。例: `4902397847281:3`",
                ephemeral=True,
            )
            return

        # 1人1発注ロック
        if user_id in _active_locks:
            locked = _active_locks[user_id]
            await interaction.response.send_message(
                f"前の発注処理が進行中です: `{locked}`\n"
                "完了またはキャンセルしてから次を入力してください。",
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
        """発注フローのメイン処理"""
        # reason がChoiceオブジェクトか生の文字列かを安全に処理
        if reason is None:
            reason_value = "restock"
            reason_label = "定期補充"
        elif hasattr(reason, "value"):
            reason_value = reason.value
            reason_label = reason.name
        else:
            # コマンドツリー未同期時に生文字列が来る場合
            reason_value = str(reason)
            reason_label = str(reason)

        # Step 1: 処理中表示
        embed = discord.Embed(
            title="発注内容を検証中...",
            description=f"対象: {len(jan_items)}品\n理由: {reason_label}",
            color=COLOR_WORKING,
        )
        await interaction.response.send_message(embed=embed)

        # Step 2: preview 実行
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
                title="タイムアウト",
                description="プレビュー取得に時間がかかりすぎました。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("order preview failed")
            embed = discord.Embed(
                title="エラー",
                description=f"プレビュー取得に失敗: {e}",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 3: プレビューJSON読み取り（exit code問わず読む）
        preview_path = stdout.decode("utf-8", errors="replace").strip()
        if not preview_path or not Path(preview_path).exists():
            err = stderr.decode("utf-8", errors="replace").strip()
            embed = discord.Embed(
                title="プレビューエラー",
                description=f"```\n{err[:800]}\n```" if err else "プレビューファイルが生成されませんでした。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        try:
            preview_data = json.loads(
                Path(preview_path).read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as e:
            embed = discord.Embed(
                title="パースエラー",
                description=f"プレビュー結果の解析に失敗: {e}",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 4: 有効な発注がなければエラーのみ表示
        orders = preview_data.get("orders", [])
        errors = preview_data.get("errors", [])

        if not orders:
            embed = discord.Embed(
                title="発注対象なし",
                description="有効な発注対象がありませんでした。",
                color=COLOR_ERROR,
            )
            if errors:
                embed.add_field(
                    name="エラー",
                    value="\n".join(f"- {e}" for e in errors[:10]),
                    inline=False,
                )
            await interaction.edit_original_response(embed=embed)
            return

        # Step 5: プレビュー Embed + ボタン表示
        user_display_name = interaction.user.display_name
        preview_embed = _build_preview_embed(preview_data, user_display_name)
        view = OrderConfirmView(user_id, preview_path)
        await interaction.edit_original_response(embed=preview_embed, view=view)

        # Step 6: ボタン待機
        await view.wait()

        if view.result == "cancel" or view.result is None:
            embed = discord.Embed(
                title="発注キャンセル",
                description=f"{len(orders)}品の発注をキャンセルしました。",
                color=COLOR_CANCEL,
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        if view.result == "timeout":
            embed = discord.Embed(
                title="タイムアウト",
                description="5分以内にボタンが押されなかったため、発注をキャンセルしました。",
                color=COLOR_CANCEL,
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        # Step 7: 発注実行
        dry_run = view.result == "dry_run"
        mode_label = "ドライラン" if dry_run else "発注"

        progress_embed = discord.Embed(
            title=f"{mode_label}実行中...",
            description=f"{len(orders)}品を処理しています。しばらくお待ちください。",
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
                title="タイムアウト",
                description="発注処理に時間がかかりすぎました。手動で確認してください。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            logger.exception("order execute failed")
            embed = discord.Embed(
                title="発注エラー",
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
            err_msg = stderr.decode("utf-8", errors="replace")[:800] if stderr else "不明なエラー"
            embed = discord.Embed(
                title="発注エラー",
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
                    title="メール送信中...",
                    description="仕入先にメールを送信しています。",
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
