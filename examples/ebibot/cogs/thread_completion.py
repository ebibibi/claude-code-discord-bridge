"""thread_completion.py — deleting a thread files the work as done (custom Cog)

Some people keep Discord threads as a to-do list and delete a thread once the
work in it is finished. Where that is the habit, the delete event is a
zero-effort completion signal, and this Cog turns it into a written record.

The constraint that shapes the design: by the time the delete event arrives the
thread's messages are already unreachable. So the record is built from what ccdb
still holds — the session row, and the transcript at
``~/.claude/projects/<project>/<session_id>.jsonl``, which contains the user
turns, the replies and the tool calls. Nothing needs to mirror Discord.

Deletions arrive in bursts (a cleanup, not one thread at a time), so they are
batched over a quiet period and handed to a single session. One session per
deleted thread would create more threads than the cleanup removed.

**Where the record goes is not decided here.** This Cog resolves the deleted
threads and hands a manifest to Claude; the instructions for what to write and
where live in an external prompt file, because that part is specific to one
person's notes and this repository is public.

**Recording is off until the user turns it on** with ``/thread-completion on``.
Deleting a thread is an everyday, destructive act, and having it silently spawn a
Claude session is a surprise; the environment variables below only decide whether
the switch exists, never whether it is thrown. The answer is stored so it survives
a restart.

Configuration (environment variables):
    THREAD_COMPLETION_CHANNEL_ID  (required) Channel to open the record thread in.
                                  The Cog is disabled when unset.
    THREAD_COMPLETION_PROMPT_FILE (optional) Path to a prompt template with
                                  ``{count}`` and ``{manifest}`` placeholders.
                                  Falls back to a generic prompt.
    THREAD_COMPLETION_DEBOUNCE    (optional) Seconds of quiet before the batch
                                  runs. Default 180.
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
from discord import app_commands
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

PROMPT_FILE = os.environ.get("THREAD_COMPLETION_PROMPT_FILE", "")

MANIFEST_DIR = str(Path.home() / "ccdb-completions")

# Settings key holding the user's answer to "should a deletion record anything?".
ENABLED_KEY = "thread_completion.enabled"

_DEFAULT_PROMPT = """\
{count} Discord thread(s) were deleted.

In this workspace a deleted thread means **the work in it is finished** — threads
are kept as a to-do list and removed once done. Write a record of that work.

`{manifest}` lists the deleted threads. Each entry has:

- `thread_id` / `thread_name` — the Discord identifiers (the thread itself is gone)
- `summary` — the opening prompt of that session
- `working_dir` — where the work happened
- `last_used_at` — when it was last touched
- `transcript_path` — the full conversation
  (`~/.claude/projects/.../<session_id>.jsonl`), containing the user turns, the
  replies and the tool calls. **This is the primary source.**

Read the manifest, then read as much of each transcript as you need — they can be
large, so don't load them whole. Where `transcript_path` is null, work from
`summary` alone and don't guess beyond it.

Record the work following this workspace's own conventions. Skip anything not
worth reading later: a short record of what mattered beats a complete one.

Report in this thread what you recorded, and what you skipped and why.
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


async def is_enabled(settings_repo: Any) -> bool:
    """Whether the user has turned recording on. Off unless they said otherwise.

    Deleting a thread is an everyday, destructive act; having it silently spawn a
    Claude session is a surprise, so consent is explicit and opt-in. Anything
    other than a stored "on" — no repo, no value, a failed read — is off, because
    the absence of an answer is not permission.
    """
    if settings_repo is None:
        return False
    try:
        return await settings_repo.get(ENABLED_KEY) == "1"
    except Exception:
        logger.exception("thread_completion: cannot read %s; treating as off", ENABLED_KEY)
        return False


async def set_enabled(settings_repo: Any, enabled: bool) -> None:
    await settings_repo.set(ENABLED_KEY, "1" if enabled else "0")


def load_template(prompt_file: str | None) -> str:
    """The instance's prompt, or the generic one.

    An unreadable path falls back rather than raising: losing the record's
    wording is recoverable, losing the whole batch is not.
    """
    if not prompt_file:
        return _DEFAULT_PROMPT
    try:
        return Path(prompt_file).read_text(encoding="utf-8")
    except OSError:
        logger.exception("thread_completion: cannot read %s; using default prompt", prompt_file)
        return _DEFAULT_PROMPT


def build_prompt(
    manifest_path: str, records: list[CompletionRecord], template: str | None = None
) -> str:
    return (template or _DEFAULT_PROMPT).format(count=len(records), manifest=manifest_path)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class ThreadCompletionCog(commands.Cog):
    """Batches thread deletions and files the finished work as a record."""

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

    @property
    def _settings_repo(self) -> Any:
        return getattr(self.components, "settings_repo", None)

    @app_commands.command(
        name="thread-completion",
        description="Record finished work when a thread is deleted (off by default)",
    )
    @app_commands.describe(switch="on, off, or leave empty to see the current state")
    @app_commands.choices(
        switch=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
    async def thread_completion(
        self, interaction: discord.Interaction, switch: str | None = None
    ) -> None:
        repo = self._settings_repo
        if repo is None:
            await interaction.response.send_message(
                "⚠️ No settings store, so the switch can't be remembered — recording stays off.",
                ephemeral=True,
            )
            return

        if switch is None:
            state = "on" if await is_enabled(repo) else "off"
            await interaction.response.send_message(
                f"Thread-completion recording is **{state}**.", ephemeral=True
            )
            return

        await set_enabled(repo, switch == "on")
        if switch == "on":
            message = (
                "✅ Thread-completion recording is **on**. Deleting a thread now files a record of "
                f"the work in it, {int(DEBOUNCE_SECONDS)}s after the last deletion."
            )
        else:
            message = "🛑 Thread-completion recording is **off**. Deleting a thread does nothing."
        await interaction.response.send_message(message, ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent) -> None:
        if payload.thread_id in self._own_threads:
            self._own_threads.discard(payload.thread_id)
            return
        if not await is_enabled(self._settings_repo):
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
        # Checked again: the switch may have been turned off during the wait, and
        # "stop" given before anything ran should be honoured.
        if not await is_enabled(self._settings_repo):
            logger.info("thread_completion: switched off while waiting; dropping %d", len(batch))
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
                prompt=build_prompt(manifest, records, load_template(PROMPT_FILE)),
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
        "ThreadCompletionCog loaded — recording is OFF until /thread-completion on; "
        "records would go to channel %d",
        THREAD_COMPLETION_CHANNEL_ID,
    )
