"""thread_completion.py — deleting a thread files the work as done (custom Cog)

胡田さんはDiscordのスレッドをTodoリストとして使っている。終わったものは自分で
削除する。つまり **削除イベントは「この作業は完了した」という、人手ゼロで発生する
高品質なラベル** である。ここではそれを拾って、Obsidianへの記録につなげる。

重要な制約: 削除イベントが届いた時点で、そのスレッドのメッセージはもう取得できない
（チャンネルごと消えている）。だから記録の材料は「ccdbが手元に持っていたもの」——
セッション行と、`~/.claude/projects/<project>/<session_id>.jsonl` のtranscript——
に限られる。transcriptにはユーザー発言もClaudeの返答もツール実行も全部入っている
ので、Discordを別途ミラーする必要はない。

まとめて消されることが多いので、削除を一定時間ためてから1回だけ記録セッションを
起こす。1件ごとにセッションを立てると、掃除のたびにスレッドが増えて本末転倒になる。

Configuration (environment variables):
    THREAD_COMPLETION_CHANNEL_ID  (required) 記録スレッドを作るチャンネル。
                                  未設定ならCogは無効。
    THREAD_COMPLETION_DEBOUNCE    (optional) 静かになってから起動するまでの秒数。
                                  既定180秒。連続削除を1バッチにまとめるため。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from claude_code_core.transcript_search import default_transcripts_root, find_transcript
from claude_discord.cogs._run_helper import run_claude_with_config
from claude_discord.cogs.headless_backend import (
    backend_factory_from_components,
    backend_settings_from_components,
    build_headless_runner,
)
from claude_discord.cogs.run_config import RunConfig
from claude_discord.thread_policy import THREAD_AUTO_ARCHIVE_MINUTES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_raw_channel_id = os.environ.get("THREAD_COMPLETION_CHANNEL_ID", "")
THREAD_COMPLETION_CHANNEL_ID: int | None = int(_raw_channel_id) if _raw_channel_id else None

DEBOUNCE_SECONDS = float(os.environ.get("THREAD_COMPLETION_DEBOUNCE", "180"))

MANIFEST_DIR = str(Path.home() / "ccdb-completions")

_PROMPT = """\
Discordのスレッドが {count} 件削除されました。

このワークスペースでは **スレッドの削除＝その作業が完了した** という意味です
（終わったものを自分で消すTodo運用）。削除された分の作業記録をObsidianに残してください。

## 材料

`{manifest}` に削除されたスレッドの一覧が入っています。各要素:

- `thread_id` / `thread_name` — Discord側の識別子（スレッド自体はもう存在しません）
- `summary` — そのセッションの最初のプロンプト
- `working_dir` — 作業ディレクトリ
- `last_used_at` — 最後にやりとりした時刻
- `transcript_path` — 会話の全文（`~/.claude/projects/.../<session_id>.jsonl`）。
  ユーザー発言・返答・ツール実行が全部入っています。**ここが一次情報です**

## やること

1. マニフェストを読み、各スレッドの transcript を確認して「実際に何をやったか」を掴む
   （transcriptは大きいことがあるので、全文をコンテキストに載せず必要な範囲を読むこと）
2. `transcript_path` が null のものは `summary` だけで判断する。無理に推測しない
3. CLAUDE.md の記録ルールに従って書く:
   - プロジェクトに紐づく作業 → 該当プロジェクトの `log.md` に詳細、`status.md` を更新
     （完了したタスクは `[ ]` → `[x]` に必ず変える）
   - デイリーノート `obsidian/01_Daily/YYYY-MM-DD.md` には wikilink + 1行サマリーだけ
4. 知識が生まれていたら 3点セット（wiki / KB / ADR）に入れる。無理に作らない
5. 雑談・確認だけで終わったもの、記録する価値がないものは **書かない**。
   「全部書く」より「後で読む価値があるものだけ書く」を優先する

## 報告

このスレッドに、何を記録したか（と、記録しなかったものと理由）を簡潔に報告してください。
報告が終わったらこのスレッドも消して構いません。
"""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletionRecord:
    """One finished conversation, as much of it as survived the deletion."""

    thread_id: int
    session_id: str | None
    summary: str | None
    working_dir: str | None
    last_used_at: str | None
    transcript_path: str | None
    thread_name: str | None = None


async def collect_records(
    thread_ids: list[int],
    session_repo: Any,
    transcripts_root: str | None,
) -> list[CompletionRecord]:
    """Turn deleted thread ids into what we still know about them.

    Threads with no session row are dropped: those are notification threads
    (おはよう, scheduler alerts, PR watches) that never held a conversation, and
    filing "work completed" for them would be a lie.
    """
    records: list[CompletionRecord] = []
    seen: set[int] = set()
    for thread_id in thread_ids:
        if thread_id in seen:
            continue
        seen.add(thread_id)
        try:
            row = await session_repo.get(thread_id)
        except Exception:
            logger.exception("thread_completion: session lookup failed for %d", thread_id)
            continue
        if row is None:
            logger.debug("thread_completion: %d had no session; not a conversation", thread_id)
            continue
        records.append(
            CompletionRecord(
                thread_id=thread_id,
                session_id=row.session_id,
                summary=row.summary,
                working_dir=row.working_dir,
                last_used_at=row.last_used_at,
                transcript_path=find_transcript(row.session_id, transcripts_root),
            )
        )
    return records


def write_manifest(records: list[CompletionRecord], directory: str, stamp: str) -> str:
    """Write the batch to disk and return its path.

    The content goes in a file rather than the prompt so a large cleanup can't
    blow up the prompt, and so customer names in a summary don't end up in
    process logs.
    """
    Path(directory).mkdir(parents=True, exist_ok=True)
    path = Path(directory) / f"completed-{stamp}.json"
    payload = {"deleted_at": stamp, "threads": [asdict(r) for r in records]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def build_prompt(manifest_path: str, records: list[CompletionRecord]) -> str:
    return _PROMPT.format(count=len(records), manifest=manifest_path)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class ThreadCompletionCog(commands.Cog):
    """Batches thread deletions and files the finished work in Obsidian."""

    def __init__(self, bot: commands.Bot, runner: object, components: object) -> None:
        self.bot = bot
        # The Cog loader hands these over as ``object``; discord.py's unions and
        # the backend protocol don't survive that, so keep them loose here.
        self.runner: Any = runner
        self.components: Any = components
        self._pending: list[int] = []
        self._flush_task: asyncio.Task[None] | None = None
        # Threads this Cog created. Deleting a record thread must not file a
        # record about filing a record.
        self._own_threads: set[int] = set()

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent) -> None:
        if payload.thread_id in self._own_threads:
            self._own_threads.discard(payload.thread_id)
            return
        self._pending.append(payload.thread_id)
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        """Restart the quiet timer — a burst of deletions becomes one batch."""
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.create_task(self._flush_after_quiet())

    async def _flush_after_quiet(self) -> None:
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return
        batch, self._pending = self._pending, []
        if not batch:
            return
        try:
            await self._file_records(batch)
        except Exception:
            logger.exception("thread_completion: failed to file %d deletions", len(batch))

    async def _file_records(self, thread_ids: list[int]) -> None:
        session_repo = getattr(self.components, "session_repo", None)
        if session_repo is None:
            logger.warning("thread_completion: no session_repo; nothing to file")
            return

        records = await collect_records(thread_ids, session_repo, default_transcripts_root())
        if not records:
            logger.info(
                "thread_completion: %d threads deleted, none held a conversation", len(thread_ids)
            )
            return

        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        manifest = write_manifest(records, MANIFEST_DIR, stamp)

        channel = self.bot.get_channel(THREAD_COMPLETION_CHANNEL_ID or 0)
        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "thread_completion: channel %s is not a text channel; manifest left at %s",
                THREAD_COMPLETION_CHANNEL_ID,
                manifest,
            )
            return

        thread = await channel.create_thread(
            name=f"🗂 完了記録 {datetime.now():%m/%d %H:%M}（{len(records)}件）",
            type=discord.ChannelType.public_thread,
            auto_archive_duration=THREAD_AUTO_ARCHIVE_MINUTES,
        )
        self._own_threads.add(thread.id)

        registry = getattr(self.components, "registry", None)
        lounge_repo = getattr(self.components, "lounge_repo", None)
        cloned_runner = await build_headless_runner(
            self.runner,
            factory=backend_factory_from_components(self.components),
            settings=backend_settings_from_components(self.components),
            thread_id=thread.id,
        )
        await run_claude_with_config(
            RunConfig(
                thread=thread,
                runner=cloned_runner,
                prompt=build_prompt(manifest, records),
                session_id=None,
                repo=session_repo,
                registry=registry,
                lounge_repo=lounge_repo,
                backend_settings=backend_settings_from_components(self.components),
            )
        )


async def setup(bot: commands.Bot, runner: object, components: object) -> None:
    """Entry point called by the custom Cog loader."""
    if THREAD_COMPLETION_CHANNEL_ID is None:
        logger.warning(
            "ThreadCompletionCog: THREAD_COMPLETION_CHANNEL_ID is not set — Cog disabled."
        )
        return

    await bot.add_cog(ThreadCompletionCog(bot, runner, components))
    logger.info(
        "ThreadCompletionCog loaded — deleted threads are filed as completed work in channel %d",
        THREAD_COMPLETION_CHANNEL_ID,
    )
