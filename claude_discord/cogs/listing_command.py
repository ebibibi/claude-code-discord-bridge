"""出品コマンド Cog — /shuppin でモール出品.

SS-17「出品データ」を唯一のデータソースとし、指定モールに出品する。
JAN未指定=未出品JAN全部、JAN指定=バリエーション自動展開。
複数JAN対応: カンマ区切りで最大5件。1JAN目→全モール→2JAN目→全モール...の順で実行。

使い方:
  /shuppin mall:Yahoo                               → 未出品JAN全部をYahooに出品
  /shuppin mall:Amazon jan:4562305934023             → そのJAN+バリエーション全部をAmazonに出品
  /shuppin mall:all jan:4562305934023,4972228232609  → 複数JANを全モールに順次出品
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# バックエンドスクリプト
PIPELINE_SCRIPT = "/home/ubuntu/ec-automation-system/scripts/shuppin_pipeline.py"
PIPELINE_PROJECT_ROOT = os.path.dirname(os.path.dirname(PIPELINE_SCRIPT))
PREVIEW_TIMEOUT = 60
UNLISTED_PREVIEW_TIMEOUT = 30   # 未出品件数取得（読み取り専用サブプロセス）
SUBMIT_TIMEOUT_BASE = 2200      # 単一モール×1JAN。最悪ケース=amazon 2アカ×840秒+マージン。
                                 # 下位層(pipeline)が先に構造化エラーで切れる設計
SUBMIT_TIMEOUT_ALL_BASE = 1500  # 全モール×1JAN (25分, Yahoo実測5分ベース)
SUBMIT_TIMEOUT_PER_JAN = 1500   # 追加JAN毎 (25分/JAN)
SUBMIT_TIMEOUT_MAX = 3600       # 上限1時間
MAX_JANS = 5                    # 複数JAN指定時の上限
PROC_KILL_WAIT = 5              # タイムアウト後のプロセス停止待ち上限(秒)

# Embed カラー
COLOR_PREVIEW = 0x3498DB   # 青
COLOR_SUCCESS = 0x2ECC71   # 緑
COLOR_ERROR = 0xE74C3C     # 赤
COLOR_CANCEL = 0x95A5A6    # グレー
COLOR_WORKING = 0xF39C12   # オレンジ

# コマンドグローバル1本ロック（別ユーザーの同時実行による同一JAN二重submitを防ぐ）
_global_lock: dict[str, object] | None = None


def _extract_inner_json(text: str) -> dict | None:
    """subprocess stdoutの末尾からJSON行を探してパースする.

    listing.py --json-output はコンパクトな1行JSONを標準出力の最後に出す
    （shuppin_pipeline.py はそれをさらに `submit.stdout` として包む）。
    ログ行と混在しているため、末尾から走査して最初に見つかった正当な
    JSONオブジェクト行を返す。見つからなければNone。
    """
    if not text:
        return None
    for line in reversed(text.strip().split("\n")):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _mall_status_lines(mall_results: dict) -> list[str]:
    """{mall: {"ok": bool}, ...} → 'OK | mall' 形式の行リストに変換する."""
    lines = []
    for mall_name, info in mall_results.items():
        ok = bool(info.get("ok")) if isinstance(info, dict) else bool(info)
        lines.append(f"{'OK' if ok else 'NG'} | {mall_name}")
    return lines


def _truncate_field(text: str, limit: int = 1024) -> str:
    """Embed field値をDiscordの上限（既定1024字）以内に切り詰める（コードフェンス込み）."""
    if not text:
        return text or ""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    marker = f"\n…({omitted}字省略)"
    cut = max(limit - len(marker), 0)
    return text[:cut] + marker


def _embed_to_plain_text(embed: discord.Embed | None, content: str | None = None) -> str:
    """edit_original_response失敗時のプレーンテキストフォールバック文面を作る."""
    parts: list[str] = []
    if content:
        parts.append(content)
    if embed is not None:
        if embed.title:
            parts.append(f"**{embed.title}**")
        if embed.description:
            parts.append(str(embed.description))
        for f in embed.fields:
            parts.append(f"**{f.name}**\n{f.value}")
    text = "\n\n".join(p for p in parts if p)
    if not text:
        text = "(表示に失敗しました。詳細はログを確認してください)"
    if len(text) > 1900:
        omitted = len(text) - 1900
        text = text[:1900] + f"\n…({omitted}字省略)"
    return text


async def _safe_edit_response(interaction: discord.Interaction, **kwargs) -> None:
    """edit_original_responseをtry/exceptで保護し、失敗時はプレーンテキストで通知する.

    Discordの1024字/6000字などのペイロード制限超過やトークン失効など、
    edit_original_response自体が例外を投げるケースでコマンド全体がクラッシュ
    (＝結果が何も表示されない)のを防ぐ。
    """
    try:
        await interaction.edit_original_response(**kwargs)
    except Exception:
        logger.exception("/shuppin: edit_original_response failed. falling back to plain text")
        fallback = _embed_to_plain_text(kwargs.get("embed"), kwargs.get("content"))
        try:
            await interaction.followup.send(content=fallback)
        except Exception:
            logger.exception("/shuppin: plain text fallback also failed")


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
        jan="JAN（カンマ区切りで最大5件。未指定=未出品JAN全部）",
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
        global _global_lock
        user_id = interaction.user.id

        # ユーザー権限チェック
        if self._allowed_user_ids is not None and user_id not in self._allowed_user_ids:
            await interaction.response.send_message(
                "このコマンドの使用権限がありません。管理者に連絡してください。",
                ephemeral=True,
            )
            return

        jan = jan.strip() if jan else ""

        # JANバリデーション（カンマ区切り複数JAN対応）
        jan_list: list[str] = []
        if jan:
            jan_list = [j.strip() for j in jan.split(",") if j.strip()]
            if len(jan_list) > MAX_JANS:
                await interaction.response.send_message(
                    f"JAN数が上限を超えています（最大{MAX_JANS}件、指定{len(jan_list)}件）。",
                    ephemeral=True,
                )
                return
            for j in jan_list:
                if not j.isdigit() or len(j) not in (8, 13):
                    await interaction.response.send_message(
                        f"JANコード `{j}` が不正です。8桁または13桁の数字で入力してください。",
                        ephemeral=True,
                    )
                    return

        # カンマ区切りを正規化（pipeline側に渡す文字列）
        jan_str = ",".join(jan_list) if jan_list else ""

        # コマンドグローバル1本ロック（誰か1人が実行中なら他ユーザーも待たせる）
        if _global_lock is not None:
            started_at: datetime = _global_lock["started_at"]  # type: ignore[assignment]
            started_ts = int(started_at.timestamp())
            await interaction.response.send_message(
                f"他の出品処理が進行中です。\n"
                f"実行者: {_global_lock['user_name']} / "
                f"開始: <t:{started_ts}:T> (<t:{started_ts}:R>)\n"
                f"内容: {_global_lock['label']}\n"
                "完了またはキャンセルしてから次を入力してください。",
                ephemeral=True,
            )
            return

        lock_label = f"{mall}"
        if jan_list:
            lock_label += f" JAN:{len(jan_list)}件" if len(jan_list) > 1 else f" JAN:{jan_list[0]}"
        else:
            lock_label += " 未出品全部"

        _global_lock = {
            "user_id": user_id,
            "user_name": str(interaction.user),
            "label": lock_label,
            "started_at": datetime.now(timezone.utc),
        }

        try:
            await self._process_listing(interaction, mall, jan_str or None, user_id, len(jan_list))
        finally:
            _global_lock = None

    async def _fetch_unlisted_summary(self, mall: str) -> dict | None:
        """未出品JANの件数と先頭5件を取得する（読み取り専用）.

        listing.py の read_tracking()/get_unlisted_jans() をそのまま呼び出す軽量
        サブプロセス。SS-17「他モール出品」シートを読むだけで、出品・書込は
        一切行わない。取得に失敗した場合はNoneを返し、呼び出し側は件数不明の
        まま処理を続行する（プレビュー表示の劣化はしても処理は止めない）。
        """
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {PIPELINE_PROJECT_ROOT!r})\n"
            "from scripts.listing import read_tracking, get_unlisted_jans, SUPPORTED_MALLS\n"
            "mall = sys.argv[1]\n"
            "tracking = read_tracking()\n"
            "malls = SUPPORTED_MALLS if mall == 'all' else [mall]\n"
            "unlisted = set()\n"
            "for m in malls:\n"
            "    unlisted.update(get_unlisted_jans(tracking, m))\n"
            "result = sorted(unlisted)\n"
            "print(json.dumps({'count': len(result), 'sample': result[:5]}, ensure_ascii=False))\n"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", script, mall,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(), timeout=UNLISTED_PREVIEW_TIMEOUT
            )
            if proc.returncode != 0:
                return None
            data = json.loads(stdout.decode("utf-8"))
            if not isinstance(data, dict) or "count" not in data:
                return None
            return data
        except asyncio.TimeoutError:
            logger.warning("/shuppin: 未出品件数の取得がタイムアウトしました")
            return None
        except (json.JSONDecodeError, ValueError, OSError):
            logger.exception("/shuppin: 未出品件数の取得に失敗しました")
            return None

    async def _process_listing(
        self,
        interaction: discord.Interaction,
        mall: str,
        jan: str | None,
        user_id: int,
        jan_count: int = 0,
    ) -> None:
        """出品フローのメイン処理"""

        # 複数JAN判定
        jan_list = jan.split(",") if jan and "," in jan else ([jan] if jan else [])
        is_multi = len(jan_list) > 1

        # Step 1: プレビュー表示
        if is_multi:
            jan_label = f"{len(jan_list)}件のJAN（1JAN毎に全モール出品）"
        elif jan:
            jan_label = f"JAN: `{jan}` (バリエーション展開)"
        else:
            jan_label = "未出品JAN全部"
        embed = discord.Embed(
            title=f"{mall.upper()} 出品準備中...",
            description=f"対象: {jan_label}",
            color=COLOR_WORKING,
        )
        await interaction.response.send_message(embed=embed)

        # Step 2: プレビュー取得
        if jan_list:
            # 各JANのプレビューを取得
            preview_data: list[tuple[str, dict | None]] = []
            for j in jan_list:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "python3", PIPELINE_SCRIPT,
                        "preview", "--jan", j,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=PREVIEW_TIMEOUT
                    )
                    if proc.returncode == 0:
                        data = json.loads(stdout.decode("utf-8"))
                        preview_data.append((j, data.get("product", {})))
                    else:
                        preview_data.append((j, None))
                except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
                    preview_data.append((j, None))

            if is_multi:
                # 複数JAN: 一覧プレビュー（カテゴリOK/NG付き）
                preview_lines = []
                for j, product in preview_data:
                    if product:
                        name = product.get("name") or "不明"
                        price = product.get("price", "?")
                        has_img = "画像OK" if product.get("has_images") else "画像NG"
                        cat_parts = []
                        for cat_key, cat_label in [
                            ("amazon_browse_node", "Amz"),
                            ("yahoo_category", "Ya"),
                            ("qoo10_category", "Q10"),
                            ("aupay_category", "au"),
                            ("temu_cat_id", "Temu"),
                        ]:
                            val = product.get(cat_key, "")
                            cat_parts.append(f"{cat_label}:\u2705" if val else f"{cat_label}:\u274c")
                        cat_str = " ".join(cat_parts)
                        preview_lines.append(f"`{j}` {name[:20]} / {price}円 / {has_img}\n　{cat_str}")
                    else:
                        preview_lines.append(f"`{j}` プレビュー取得失敗")
                embed = discord.Embed(
                    title=f"{len(jan_list)}件のJAN — {mall.upper()}出品",
                    description="\n".join(preview_lines),
                    color=COLOR_PREVIEW,
                )
            else:
                # 単一JAN: 詳細プレビュー
                j, product = preview_data[0]
                if product:
                    product_name = product.get("name") or f"JAN: {j}"
                    price = product.get("price", "?")
                    has_images = product.get("has_images", False)
                    has_desc = product.get("has_description", False)
                    cat_status = []
                    for cat_key, cat_label in [
                        ("amazon_browse_node", "Amazon"),
                        ("yahoo_category", "Yahoo"),
                        ("qoo10_category", "Qoo10"),
                        ("aupay_category", "auPAY"),
                        ("temu_cat_id", "Temu"),
                    ]:
                        val = product.get(cat_key, "")
                        cat_status.append(f"{cat_label}:\u2705" if val else f"{cat_label}:\u274c")
                    embed = discord.Embed(
                        title=f"{product_name}",
                        description=(
                            f"**JAN:** `{j}`\n"
                            f"**売価:** {price}円\n"
                            f"**画像:** {'あり' if has_images else '未設定'} / **説明文:** {'あり' if has_desc else '未設定'}\n"
                            f"**カテゴリID:** {' / '.join(cat_status)}"
                        ),
                        color=COLOR_PREVIEW,
                    )
                else:
                    embed = discord.Embed(
                        title=f"JAN: {j}",
                        description="プレビュー取得失敗。出品は続行可能です。",
                        color=COLOR_PREVIEW,
                    )
        else:
            # JAN未指定 = 未出品JAN全部が対象。件数不明のまま確定させない。
            unlisted = await self._fetch_unlisted_summary(mall)
            if unlisted is None:
                unlisted_desc = (
                    "未出品JAN件数の取得に失敗しました（SS-17参照エラーの可能性）。\n"
                    "件数は出品実行時に確定します。"
                )
            elif unlisted["count"] == 0:
                unlisted_desc = "未出品のJANはありません（対象0件）。"
            else:
                sample = unlisted["sample"]
                sample_text = "\n".join(f"`{j}`" for j in sample)
                rest = unlisted["count"] - len(sample)
                if rest > 0:
                    sample_text += f"\n...他{rest}件"
                unlisted_desc = f"**未出品JAN: {unlisted['count']}件**\n{sample_text}"

            if mall == "all":
                embed = discord.Embed(
                    title="ALL SHOP 全モール一括出品",
                    description=(
                        "**全6モール**が対象。Amazon / Yahoo / Qoo10 / auPAY / Temu / メルカリ\n\n"
                        f"{unlisted_desc}\n\n"
                        "データ不備のモールは自動スキップされます。"
                    ),
                    color=COLOR_PREVIEW,
                )
            else:
                embed = discord.Embed(
                    title=f"{mall.upper()} 一括出品",
                    description=f"SS-17「他モール出品」で未出品のJANを出品します。\n\n{unlisted_desc}",
                    color=COLOR_PREVIEW,
                )

        mall_label = "全モール（Amazon/Yahoo/Qoo10/auPAY/Temu/メルカリ）" if mall == "all" else mall.upper()
        embed.set_footer(text=f"出品先: {mall_label}")

        # Step 3: 確認ボタン
        view = ListingConfirmView(user_id, mall, jan)
        await _safe_edit_response(interaction, embed=embed, view=view)

        await view.wait()

        if view.result == "cancel" or view.result is None:
            embed = discord.Embed(
                title="出品キャンセル",
                description=f"モール: {mall.upper()}",
                color=COLOR_CANCEL,
            )
            await _safe_edit_response(interaction, embed=embed, view=None)
            return

        if view.result == "timeout":
            embed = discord.Embed(
                title="タイムアウト",
                description="5分以内にボタンが押されなかったため、キャンセルしました。",
                color=COLOR_CANCEL,
            )
            await _safe_edit_response(interaction, embed=embed, view=None)
            return

        # Step 4: 出品実行
        dry_run = view.result == "dry_run"
        mode_label = "ドライラン" if dry_run else "出品"

        mall_display = "全モール" if mall == "all" else mall.upper()
        n_jans = max(len(jan_list), 1)

        # タイムアウト動的計算（Yahoo実測5分/JANベース）
        base = SUBMIT_TIMEOUT_ALL_BASE if mall == "all" else SUBMIT_TIMEOUT_BASE
        timeout = min(base + (n_jans - 1) * SUBMIT_TIMEOUT_PER_JAN, SUBMIT_TIMEOUT_MAX)

        time_est = f"（推定 約{timeout // 60}分）" if is_multi or mall == "all" else ""
        progress_desc = f"モール: {mall_display}\n"
        if is_multi:
            progress_desc += f"JAN: {n_jans}件（1JAN毎に全モール出品）\n"
        progress_desc += f"しばらくお待ちください。{time_est}"

        progress_embed = discord.Embed(
            title=f"{mode_label}実行中...",
            description=progress_desc,
            color=COLOR_WORKING,
        )
        await _safe_edit_response(interaction, embed=progress_embed, view=None)

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
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            # タイムアウトしたプロセスを確実に止める（表示の裏で出品が続行する事故を防ぐ）
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=PROC_KILL_WAIT)
            except ProcessLookupError:
                pass
            except Exception:
                logger.exception("/shuppin: タイムアウト後のプロセス停止に失敗しました")
            embed = discord.Embed(
                title="タイムアウト",
                description=(
                    f"出品処理がタイムアウトしました（{timeout // 60}分）。\n"
                    "プロセスは停止済みです。手動で状況を確認してください。"
                ),
                color=COLOR_ERROR,
            )
            await _safe_edit_response(interaction, embed=embed)
            return
        except Exception as e:
            logger.exception("shuppin submit failed")
            embed = discord.Embed(
                title="出品エラー",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await _safe_edit_response(interaction, embed=embed)
            return

        # Step 5: 結果表示
        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        try:
            result_data = json.loads(stdout_text)
        except (json.JSONDecodeError, ValueError):
            result_data = None

        # returncodeだけでなく、内側JSON（shuppin_pipelineのstdout）のokを正とする。
        # listing.py/shuppin_pipeline.pyはモールが一部失敗してもexit 0を返すことがある
        # ため、JSONが取れていればreturncode≠0でもそちらを解釈する（将来listing.py側が
        # exit1化しても両建てで正しく動く）。
        if result_data is not None and "ok" in result_data:
            overall_ok = bool(result_data["ok"])
        else:
            overall_ok = proc.returncode == 0

        if result_data is not None and result_data.get("multi"):
            # 複数JAN結果
            jan_results = result_data.get("results", [])
            ok_count = sum(1 for r in jan_results if r.get("ok"))
            ng_count = len(jan_results) - ok_count

            if ng_count == 0:
                title, color = f"{mode_label}完了", COLOR_SUCCESS
            elif ok_count == 0:
                title, color = f"{mode_label}失敗", COLOR_ERROR
            else:
                title, color = f"{mode_label}一部失敗", COLOR_WORKING

            result_embed = discord.Embed(
                title=title,
                description=(
                    f"モール: **{mall_display}**\n"
                    f"JAN: {len(jan_results)}件 (成功: {ok_count} / 失敗: {ng_count})"
                ),
                color=color,
            )

            # JAN毎の結果サマリー（内側JSONからモール別内訳が取れれば併記）
            lines = []
            for r in jan_results:
                status = "OK" if r.get("ok") else "NG"
                line = f"{status} | `{r.get('jan', '?')}`"
                inner = _extract_inner_json(r.get("stdout", ""))
                mall_results = inner.get("results") if inner else None
                if mall_results:
                    bits = ", ".join(
                        f"{m}:{'OK' if v.get('ok') else 'NG'}" for m, v in mall_results.items()
                    )
                    line += f" ({bits})"
                lines.append(line)
            if lines:
                result_embed.add_field(
                    name="JAN毎の結果",
                    value=_truncate_field("\n".join(lines[:10])),
                    inline=False,
                )
            result_embed.set_footer(text="/shuppin mall:モール名 で次の出品へ")
            await _safe_edit_response(interaction, embed=result_embed)

        elif result_data is not None:
            # 単一JAN or JAN未指定
            submit_info = result_data.get("submit", {}) or {}
            submit_ok = bool(submit_info.get("ok", overall_ok))
            submit_stdout = submit_info.get("stdout", stdout_text)
            # listing.py --json-output が出す内側JSON（モール別ok）を解釈する
            inner = _extract_inner_json(submit_stdout)
            mall_results = inner.get("results") if inner else None
            mall_ok_count = (
                sum(1 for v in mall_results.values() if v.get("ok")) if mall_results else None
            )

            if not submit_ok:
                title, color = f"{mode_label}失敗", COLOR_ERROR
            elif mall_results and 0 < mall_ok_count < len(mall_results):
                title, color = f"{mode_label}一部失敗", COLOR_WORKING
            else:
                title, color = f"{mode_label}完了", COLOR_SUCCESS

            result_embed = discord.Embed(
                title=title,
                description=f"モール: **{mall_display}**",
                color=color,
            )

            if mall_results:
                result_embed.add_field(
                    name="モール別結果",
                    value=_truncate_field("\n".join(_mall_status_lines(mall_results))),
                    inline=False,
                )
            else:
                # モール別内訳が取れない場合は error/message を拾って表示
                notice = (
                    result_data.get("error")
                    or (inner.get("message") if inner else None)
                    or (inner.get("error") if inner else None)
                )
                if notice:
                    result_embed.add_field(
                        name="エラー" if not submit_ok else "結果",
                        value=_truncate_field(str(notice)),
                        inline=False,
                    )

            if submit_stdout:
                lines = submit_stdout.strip().split("\n")
                summary_lines = [ln for ln in lines[-15:] if ln.strip()]
                if summary_lines:
                    result_embed.add_field(
                        name="ログ抜粋",
                        value=_truncate_field(f"```\n{chr(10).join(summary_lines[-10:])}\n```"),
                        inline=False,
                    )

            skip_list = inner.get("skipped") if inner else None
            if skip_list:
                result_embed.add_field(
                    name="スキップ（データ不備）",
                    value=_truncate_field(", ".join(skip_list)),
                    inline=False,
                )

            result_embed.set_footer(text="/shuppin mall:モール名 で次の出品へ")
            await _safe_edit_response(interaction, embed=result_embed)

        else:
            # JSONパース失敗（想定外の出力形式）— returncodeベースにフォールバック
            if overall_ok:
                result_embed = discord.Embed(
                    title=f"{mode_label}完了（詳細不明）",
                    description=(
                        f"モール: **{mall_display}**\n"
                        "JSON出力の解析に失敗しました。ログ抜粋を確認してください。"
                    ),
                    color=COLOR_WORKING,
                )
                if stdout_text:
                    tail_lines = stdout_text.strip().split("\n")[-15:]
                    summary_lines = [ln for ln in tail_lines if ln.strip()]
                    if summary_lines:
                        result_embed.add_field(
                            name="ログ抜粋",
                            value=_truncate_field(f"```\n{chr(10).join(summary_lines[-10:])}\n```"),
                            inline=False,
                        )
                await _safe_edit_response(interaction, embed=result_embed)
            else:
                err_msg = stderr_text[:800] if stderr_text else "不明なエラー"
                embed = discord.Embed(
                    title="出品エラー",
                    description=f"```\n{err_msg}\n```",
                    color=COLOR_ERROR,
                )
                await _safe_edit_response(interaction, embed=embed)

        logger.info(
            "/shuppin by %s: mall=%s, jan=%s, jan_count=%d, result=%s, ok=%s",
            interaction.user.name, mall, jan or "all-unlisted",
            n_jans, view.result, overall_ok,
        )
