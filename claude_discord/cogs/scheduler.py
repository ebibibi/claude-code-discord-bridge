"""SchedulerCog — SQLite-backed periodic Claude Code task executor.

Design:
- Tasks are stored in ``scheduled_tasks`` DB table and registered via REST API
  (Claude Code calls POST /api/tasks from within a chat session).
- A single 30-second master loop checks for due tasks and spawns them.
- ``discord.ext.tasks`` is used only for the master loop — individual tasks
  are not @tasks.loop decorated (they are runtime-dynamic).
- Claude handles all domain logic (what to check, how to deduplicate).
  ccdb only manages scheduling.

See: Issue #90, CLAUDE.md §Key Design Decisions #7-9.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from ._run_helper import run_claude_with_config
from .run_config import RunConfig

if TYPE_CHECKING:
    from ..claude.runner import ClaudeRunner
    from ..database.task_repo import TaskRepository

logger = logging.getLogger(__name__)

# How often the master loop wakes up to check for due tasks.
MASTER_LOOP_INTERVAL_SECONDS = 30


class SchedulerCog(commands.Cog):
    """Cog that periodically runs Claude Code tasks stored in SQLite.

    Args:
        bot: The Discord bot instance.
        runner: Base ClaudeRunner to clone per task execution.
        repo: TaskRepository for reading/updating scheduled tasks.
    """

    def __init__(
        self,
        bot: commands.Bot,
        runner: ClaudeRunner,
        *,
        repo: TaskRepository,
    ) -> None:
        self.bot = bot
        self.runner = runner
        self.repo = repo
        # Track in-flight tasks to avoid double-running the same task_id.
        self._running: set[int] = set()

    async def cog_load(self) -> None:
        """Start the master loop when the Cog is loaded."""
        self._master_loop.start()
        logger.info("SchedulerCog loaded — master loop started")

    def cog_unload(self) -> None:
        """Cancel the master loop when the Cog is unloaded."""
        self._master_loop.cancel()
        logger.info("SchedulerCog unloaded — master loop stopped")

    @tasks.loop(seconds=MASTER_LOOP_INTERVAL_SECONDS)
    async def _master_loop(self) -> None:
        """Wake up every 30 s, find due tasks, and spawn them concurrently."""
        due = await self.repo.get_due()
        if not due:
            return

        logger.info("SchedulerCog: %d task(s) due", len(due))
        for task in due:
            task_id: int = task["id"]
            if task_id in self._running:
                logger.debug("Task %d still running — skipping", task_id)
                continue

            # Advance next_run_at *before* spawning to prevent duplicate runs
            # if the loop fires again before the task finishes.
            await self.repo.update_next_run(task_id, interval_seconds=task["interval_seconds"])

            asyncio.create_task(
                self._run_task(task),
                name=f"ccdb-scheduler-{task_id}",
            )

    @_master_loop.before_loop
    async def _before_master_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_task(self, task: dict) -> None:
        """Execute a single scheduled task in a Discord thread."""
        task_id: int = task["id"]
        self._running.add(task_id)
        try:
            channel = self.bot.get_channel(task["channel_id"])
            if channel is None:
                logger.warning(
                    "SchedulerCog: channel %d not found for task %d (%s)",
                    task["channel_id"],
                    task_id,
                    task["name"],
                )
                return
            if not isinstance(channel, discord.TextChannel):
                logger.warning("SchedulerCog: channel %d is not a TextChannel", task["channel_id"])
                return

            # Post a starter message first so the thread appears in the channel
            # timeline and shows up in the left sidebar under the parent channel.
            # channel.create_thread() without a message only appears in the
            # Threads panel (🧵), not in the channel list.
            starter = await channel.send(f"🔄 **[Scheduled]** `{task['name']}`")
            thread = await starter.create_thread(
                name=f"[Scheduled] {task['name']}",
            )

            cloned = self.runner.clone()
            if task.get("working_dir"):
                cloned.working_dir = task["working_dir"]

            registry = getattr(self.bot, "session_registry", None)
            await run_claude_with_config(
                RunConfig(
                    thread=thread,
                    runner=cloned,
                    repo=None,  # scheduled tasks don't persist session state
                    prompt=task["prompt"],
                    session_id=None,
                    registry=registry,
                )
            )

        except Exception:
            logger.exception("SchedulerCog: task %d (%s) failed", task_id, task["name"])
        finally:
            self._running.discard(task_id)
