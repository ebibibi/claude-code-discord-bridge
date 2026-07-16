"""Tests for ListingCommandCog (/shuppin) — 結果表示の嘘とクラッシュの根絶.

対象の既知バグ（TakaBrain調査正本: shuppin深掘り_2026-07-17.md §3）:
  - 部分失敗が緑の完了に化ける（listing.py exit0 + bot側returncodeのみ判定）
  - 結果Embed field 1024字超でDiscord 400 → 結果表示クラッシュ
  - タイムアウト時にproc.kill()せず、表示の裏で出品続行
  - JAN未指定プレビューが件数非表示のまま全量出品確定可能
  - 別ユーザー同時実行で同一JAN二重submit可（ロックがユーザー単位）
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs import listing_command
from claude_discord.cogs.listing_command import (
    COLOR_ERROR,
    ListingCommandCog,
    ListingConfirmView,
    _embed_to_plain_text,
    _extract_inner_json,
    _mall_status_lines,
    _safe_edit_response,
    _truncate_field,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cog() -> ListingCommandCog:
    """SHUPPIN_ALLOWED_USER_IDS/DISCORD_OWNER_ID未設定=全ユーザー許可のCogを返す."""
    bot = MagicMock()
    return ListingCommandCog(bot)


def _make_interaction(user_id: int = 1, user_label: str = "user") -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.user.name = user_label
    interaction.user.__str__ = MagicMock(return_value=f"{user_label}#0000")
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    """asyncio.create_subprocess_exec が返すプロセスオブジェクトのモック."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    return proc


def _preview_json(jan: str = "4562305934023") -> bytes:
    return json.dumps({
        "ok": True,
        "jan": jan,
        "product": {
            "found": True, "name": "テスト商品", "price": "1000",
            "has_images": True, "has_description": True,
        },
    }, ensure_ascii=False).encode("utf-8")


@pytest.fixture(autouse=True)
def _reset_global_lock():
    """テスト間でグローバルロックが漏れないようにする."""
    listing_command._global_lock = None
    yield
    listing_command._global_lock = None


@pytest.fixture(autouse=True)
def _auto_confirm(monkeypatch):
    """ListingConfirmView.wait() を即時「出品する」確定にする."""

    async def _wait(self):
        self.result = "confirm"

    monkeypatch.setattr(ListingConfirmView, "wait", _wait)


# ---------------------------------------------------------------------------
# _extract_inner_json
# ---------------------------------------------------------------------------


class TestExtractInnerJson:
    def test_empty_text_returns_none(self) -> None:
        assert _extract_inner_json("") is None
        assert _extract_inner_json(None) is None  # type: ignore[arg-type]

    def test_no_json_line_returns_none(self) -> None:
        text = "line1\nline2\nnot json at all"
        assert _extract_inner_json(text) is None

    def test_finds_compact_json_among_log_noise(self) -> None:
        inner = {"ok": True, "results": {"yahoo": {"ok": True}, "amazon": {"ok": False}}}
        text = "SS-17 読み取り中...\n対象: 3商品\n" + json.dumps(inner, ensure_ascii=False)
        assert _extract_inner_json(text) == inner

    def test_ignores_pretty_printed_multiline_json(self) -> None:
        # shuppin_pipeline.py 自身の出力(indent=2)は複数行になるため
        # 単一行走査では拾わない(listing.pyの--json-output専用の想定通り)
        text = json.dumps({"ok": True, "results": {}}, indent=2)
        assert _extract_inner_json(text) is None

    def test_picks_last_valid_json_line_when_multiple(self) -> None:
        text = '{"stale": true}\nsome log\n{"ok": false, "results": {"yahoo": {"ok": false}}}'
        result = _extract_inner_json(text)
        assert result == {"ok": False, "results": {"yahoo": {"ok": False}}}


# ---------------------------------------------------------------------------
# _truncate_field
# ---------------------------------------------------------------------------


class TestTruncateField:
    def test_short_text_unchanged(self) -> None:
        assert _truncate_field("short") == "short"

    def test_empty_text(self) -> None:
        assert _truncate_field("") == ""

    def test_over_limit_truncated_to_limit(self) -> None:
        text = "a" * 2000
        result = _truncate_field(text)
        assert len(result) <= 1024
        assert "字省略" in result

    def test_fenced_code_block_also_bounded(self) -> None:
        text = "```\n" + ("line\n" * 500) + "```"
        assert len(text) > 1024
        result = _truncate_field(text)
        assert len(result) <= 1024

    def test_custom_limit(self) -> None:
        text = "b" * 100
        result = _truncate_field(text, limit=50)
        assert len(result) <= 50


# ---------------------------------------------------------------------------
# _mall_status_lines
# ---------------------------------------------------------------------------


class TestMallStatusLines:
    def test_ok_and_ng_lines(self) -> None:
        lines = _mall_status_lines({"yahoo": {"ok": True}, "amazon": {"ok": False}})
        assert lines == ["OK | yahoo", "NG | amazon"]

    def test_empty_dict(self) -> None:
        assert _mall_status_lines({}) == []


# ---------------------------------------------------------------------------
# _safe_edit_response — edit_original_response保護
# ---------------------------------------------------------------------------


class TestSafeEditResponse:
    @pytest.mark.asyncio
    async def test_success_path_no_fallback(self) -> None:
        interaction = _make_interaction()
        embed = discord.Embed(title="OK")

        await _safe_edit_response(interaction, embed=embed)

        interaction.edit_original_response.assert_called_once_with(embed=embed)
        interaction.followup.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_falls_back_to_plain_text(self) -> None:
        interaction = _make_interaction()
        interaction.edit_original_response = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(status=400), "payload too large")
        )
        embed = discord.Embed(title="出品完了", description="モール: **YAHOO**")
        embed.add_field(name="結果", value="OK", inline=False)

        await _safe_edit_response(interaction, embed=embed)

        interaction.followup.send.assert_called_once()
        fallback_text = interaction.followup.send.call_args.kwargs["content"]
        assert "出品完了" in fallback_text
        assert "結果" in fallback_text

    @pytest.mark.asyncio
    async def test_fallback_itself_failing_does_not_raise(self) -> None:
        """followup.send も失敗しても例外を外に漏らさない(クラッシュ根絶)."""
        interaction = _make_interaction()
        interaction.edit_original_response = AsyncMock(side_effect=RuntimeError("boom"))
        interaction.followup.send = AsyncMock(side_effect=RuntimeError("boom again"))

        await _safe_edit_response(interaction, embed=discord.Embed(title="x"))  # should not raise

    def test_embed_to_plain_text_truncates_long_embed(self) -> None:
        embed = discord.Embed(title="t")
        embed.add_field(name="f", value="x" * 3000, inline=False)
        text = _embed_to_plain_text(embed)
        assert len(text) <= 1900 + 30  # マーカー分の余裕を見た上限


# ---------------------------------------------------------------------------
# _fetch_unlisted_summary — JAN未指定プレビューの件数取得（読み取り専用）
# ---------------------------------------------------------------------------


class TestFetchUnlistedSummary:
    @pytest.mark.asyncio
    async def test_returns_count_and_sample(self, monkeypatch) -> None:
        cog = _make_cog()
        proc = _make_proc(
            stdout=json.dumps({"count": 42, "sample": ["111", "222"]}).encode(), returncode=0
        )
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
        )

        result = await cog._fetch_unlisted_summary("yahoo")

        assert result == {"count": 42, "sample": ["111", "222"]}

    @pytest.mark.asyncio
    async def test_nonzero_returncode_returns_none(self, monkeypatch) -> None:
        cog = _make_cog()
        proc = _make_proc(stdout=b"", stderr=b"traceback...", returncode=1)
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
        )

        result = await cog._fetch_unlisted_summary("all")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, monkeypatch) -> None:
        cog = _make_cog()
        proc = _make_proc()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
        )

        result = await cog._fetch_unlisted_summary("amazon")

        assert result is None

    @pytest.mark.asyncio
    async def test_garbage_stdout_returns_none(self, monkeypatch) -> None:
        cog = _make_cog()
        proc = _make_proc(stdout=b"not json", returncode=0)
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
        )

        result = await cog._fetch_unlisted_summary("qoo10")

        assert result is None


# ---------------------------------------------------------------------------
# ① JSON ok=false 時にNG表示（returncode==0でも「嘘」の完了表示にしない）
# ---------------------------------------------------------------------------


class TestResultInterpretationHonesty:
    @pytest.mark.asyncio
    async def test_ok_false_with_returncode_zero_shows_failure(self, monkeypatch) -> None:
        """listing.py/shuppin_pipeline.pyがexit0でもJSON ok=falseならNG表示にする."""
        cog = _make_cog()
        interaction = _make_interaction()

        preview_proc = _make_proc(stdout=_preview_json(), returncode=0)
        submit_stdout = json.dumps({
            "ok": False,
            "mall": "yahoo",
            "multi": False,
            "jan": "4562305934023",
            "submit": {
                "ok": False,
                "stdout": '対象0商品\n{"ok": false, "error": "preflight BLOCK"}',
                "stderr": "",
            },
        }, ensure_ascii=False).encode("utf-8")
        # 既知バグ再現: 実際には失敗しているのにプロセス自体はexit0で終わる
        submit_proc = _make_proc(stdout=submit_stdout, returncode=0)

        create_mock = AsyncMock(side_effect=[preview_proc, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        await cog._process_listing(interaction, "yahoo", "4562305934023", 1, 1)

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        assert "失敗" in embed.title
        assert embed.color.value == COLOR_ERROR
        assert any("preflight BLOCK" in f.value for f in embed.fields)

    @pytest.mark.asyncio
    async def test_mall_level_ok_ng_is_rendered(self, monkeypatch) -> None:
        """内側JSON(listing.py --json-output)のresults.<mall>.okをモール別に表示する."""
        cog = _make_cog()
        interaction = _make_interaction()

        preview_proc = _make_proc(stdout=_preview_json(), returncode=0)
        inner = {"ok": False, "results": {"yahoo": {"ok": True}, "amazon": {"ok": False}}}
        submit_stdout = json.dumps({
            "ok": False,
            "mall": "all",
            "multi": False,
            "jan": "4562305934023",
            "submit": {"ok": False, "stdout": json.dumps(inner, ensure_ascii=False), "stderr": ""},
        }, ensure_ascii=False).encode("utf-8")
        submit_proc = _make_proc(stdout=submit_stdout, returncode=0)

        create_mock = AsyncMock(side_effect=[preview_proc, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        await cog._process_listing(interaction, "all", "4562305934023", 1, 1)

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        mall_field = next(f for f in embed.fields if f.name == "モール別結果")
        assert "OK | yahoo" in mall_field.value
        assert "NG | amazon" in mall_field.value

    @pytest.mark.asyncio
    async def test_all_ok_shows_success(self, monkeypatch) -> None:
        cog = _make_cog()
        interaction = _make_interaction()

        preview_proc = _make_proc(stdout=_preview_json(), returncode=0)
        submit_stdout = json.dumps({
            "ok": True,
            "mall": "yahoo",
            "multi": False,
            "jan": "4562305934023",
            "submit": {"ok": True, "stdout": "出品完了\n", "stderr": ""},
        }, ensure_ascii=False).encode("utf-8")
        submit_proc = _make_proc(stdout=submit_stdout, returncode=0)

        create_mock = AsyncMock(side_effect=[preview_proc, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        await cog._process_listing(interaction, "yahoo", "4562305934023", 1, 1)

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        assert "完了" in embed.title
        assert "失敗" not in embed.title


# ---------------------------------------------------------------------------
# ② 1024字切り詰め（クラッシュ根絶）
# ---------------------------------------------------------------------------


class TestFieldTruncationIntegration:
    @pytest.mark.asyncio
    async def test_huge_submit_log_is_truncated_in_final_embed(self, monkeypatch) -> None:
        cog = _make_cog()
        interaction = _make_interaction()

        preview_proc = _make_proc(stdout=_preview_json(), returncode=0)
        huge_log = "\n".join(f"line {i} " + "x" * 60 for i in range(200))
        submit_stdout = json.dumps({
            "ok": True,
            "mall": "yahoo",
            "multi": False,
            "jan": "4562305934023",
            "submit": {"ok": True, "stdout": huge_log, "stderr": ""},
        }, ensure_ascii=False).encode("utf-8")
        submit_proc = _make_proc(stdout=submit_stdout, returncode=0)

        create_mock = AsyncMock(side_effect=[preview_proc, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        await cog._process_listing(interaction, "yahoo", "4562305934023", 1, 1)

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        assert embed.fields, "resultにfieldが1つも無い"
        for f in embed.fields:
            assert len(f.value) <= 1024

    @pytest.mark.asyncio
    async def test_huge_multi_jan_summary_is_truncated(self, monkeypatch) -> None:
        cog = _make_cog()
        interaction = _make_interaction()

        preview_procs = [_make_proc(stdout=_preview_json(jan), returncode=0)
                          for jan in ("11111111", "22222222")]
        jan_results = []
        for i in range(2):
            jan_results.append({
                "jan": f"1111111{i}", "index": i + 1, "total": 2, "ok": i % 2 == 0,
                "stdout": "x" * 3000, "stderr": "",
            })
        submit_stdout = json.dumps({
            "ok": False, "mall": "all", "multi": True,
            "jan_count": 2, "results": jan_results,
        }, ensure_ascii=False).encode("utf-8")
        submit_proc = _make_proc(stdout=submit_stdout, returncode=0)

        create_mock = AsyncMock(side_effect=[*preview_procs, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        await cog._process_listing(interaction, "all", "11111111,22222222", 1, 2)

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        for f in embed.fields:
            assert len(f.value) <= 1024


# ---------------------------------------------------------------------------
# ③ タイムアウト時のkill呼び出し
# ---------------------------------------------------------------------------


class TestTimeoutKillsProcess:
    @pytest.mark.asyncio
    async def test_timeout_calls_proc_kill(self, monkeypatch) -> None:
        cog = _make_cog()
        interaction = _make_interaction()

        preview_proc = _make_proc(stdout=_preview_json(), returncode=0)
        submit_proc = _make_proc(returncode=0)
        submit_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        create_mock = AsyncMock(side_effect=[preview_proc, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        await cog._process_listing(interaction, "yahoo", "4562305934023", 1, 1)

        submit_proc.kill.assert_called_once()

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        assert "タイムアウト" in embed.title
        assert "停止済み" in embed.description

    @pytest.mark.asyncio
    async def test_kill_process_lookup_error_is_swallowed(self, monkeypatch) -> None:
        """既にプロセスが終了していた場合のProcessLookupErrorはクラッシュにしない."""
        cog = _make_cog()
        interaction = _make_interaction()

        preview_proc = _make_proc(stdout=_preview_json(), returncode=0)
        submit_proc = _make_proc(returncode=0)
        submit_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        submit_proc.kill = MagicMock(side_effect=ProcessLookupError())

        create_mock = AsyncMock(side_effect=[preview_proc, submit_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_mock)

        # 例外を投げずに完走すること
        await cog._process_listing(interaction, "yahoo", "4562305934023", 1, 1)

        final_call = interaction.edit_original_response.call_args_list[-1]
        embed = final_call.kwargs["embed"]
        assert "タイムアウト" in embed.title


# ---------------------------------------------------------------------------
# ④ グローバルロックの排他と解放
# ---------------------------------------------------------------------------


class TestGlobalLock:
    @pytest.mark.asyncio
    async def test_second_user_blocked_while_first_is_running(self, monkeypatch) -> None:
        cog = _make_cog()
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_process_listing(self, interaction, mall, jan, user_id, jan_count=0):
            started.set()
            await release.wait()

        monkeypatch.setattr(ListingCommandCog, "_process_listing", fake_process_listing)

        interaction1 = _make_interaction(user_id=1, user_label="alice")
        interaction2 = _make_interaction(user_id=2, user_label="bob")

        task1 = asyncio.create_task(
            cog.shuppin.callback(cog, interaction1, mall="yahoo", jan="")
        )
        await asyncio.wait_for(started.wait(), timeout=2)

        # ロック保持中: 別ユーザーは拒否される
        await cog.shuppin.callback(cog, interaction2, mall="amazon", jan="")

        interaction2.response.send_message.assert_called_once()
        msg = interaction2.response.send_message.call_args.args[0]
        assert "進行中" in msg
        assert "alice#0000" in msg

        # 解放
        release.set()
        await asyncio.wait_for(task1, timeout=2)

        assert listing_command._global_lock is None

    @pytest.mark.asyncio
    async def test_lock_released_via_finally_even_on_exception(self, monkeypatch) -> None:
        cog = _make_cog()

        async def raising_process_listing(self, interaction, mall, jan, user_id, jan_count=0):
            raise RuntimeError("boom")

        monkeypatch.setattr(ListingCommandCog, "_process_listing", raising_process_listing)
        interaction = _make_interaction(user_id=1)

        with pytest.raises(RuntimeError):
            await cog.shuppin.callback(cog, interaction, mall="yahoo", jan="")

        assert listing_command._global_lock is None

    @pytest.mark.asyncio
    async def test_lock_free_after_release_allows_next_run(self, monkeypatch) -> None:
        cog = _make_cog()
        calls: list[int] = []

        async def fake_process_listing(self, interaction, mall, jan, user_id, jan_count=0):
            calls.append(user_id)

        monkeypatch.setattr(ListingCommandCog, "_process_listing", fake_process_listing)

        interaction1 = _make_interaction(user_id=1)
        interaction2 = _make_interaction(user_id=2)

        await cog.shuppin.callback(cog, interaction1, mall="yahoo", jan="")
        await cog.shuppin.callback(cog, interaction2, mall="amazon", jan="")

        assert calls == [1, 2]
        interaction2.response.send_message.assert_not_called()
