"""AutoUpgradeCog — Webhook-triggered package upgrade + optional restart.

Generic pattern for auto-upgrading a pip/uv package when a webhook fires.
Typical use: upstream library pushes a new release → CI sends webhook → bot upgrades itself.

Security design:
- Only processes messages with a webhook_id
- Optional webhook_id allowlist
- All commands are hardcoded or from UpgradeConfig — no user input in subprocess args
- Uses create_subprocess_exec (never shell=True)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

import discord
from discord.ext import commands

from ..protocols import DrainAware

logger = logging.getLogger(__name__)

# Default timeout for each subprocess step (seconds).
_STEP_TIMEOUT = 120


@dataclass(frozen=True)
class UpgradeConfig:
    """Configuration for auto-upgrade behaviour.

    Attributes:
        package_name: The pip/uv package name to upgrade.
        trigger_prefix: Webhook message prefix that triggers the upgrade.
        working_dir: Directory to run upgrade commands in.
        upgrade_command: Custom upgrade command as arg list.
            Defaults to ["uv", "lock", "--upgrade-package", <package_name>].
        sync_command: Custom sync command as arg list.
            Defaults to ["uv", "sync"].
        restart_command: Optional restart command
            (e.g. ["sudo", "systemctl", "restart", "my.service"]).
        allowed_webhook_ids: Optional set of allowed webhook IDs.
        channel_ids: Optional set of channel IDs to listen in.
        step_timeout: Timeout in seconds for each subprocess step.
        restart_approval: If True, wait for a user to react with ✅ before
            restarting. Useful when the bot is updated from within its own
            Discord sessions (self-update pattern). Default: False.
    """

    package_name: str
    trigger_prefix: str = "🔄 upgrade"
    working_dir: str = "."
    upgrade_command: list[str] | None = None
    sync_command: list[str] | None = None
    restart_command: list[str] | None = None
    allowed_webhook_ids: set[int] | None = None
    channel_ids: set[int] | None = None
    step_timeout: int = _STEP_TIMEOUT
    restart_approval: bool = False
    upgrade_approval: bool = False
    """If True, wait for a user to react with ✅ before running any upgrade
    commands. Useful when you want manual control over when updates are applied.
    When False (default), upgrade steps run automatically on webhook trigger."""


class AutoUpgradeCog(commands.Cog):
    """Cog that auto-upgrades a package when triggered by a Discord webhook.

    Usage::

        config = UpgradeConfig(
            package_name="claude-code-discord-bridge",
            trigger_prefix="🔄 ebibot-upgrade",
            working_dir="/home/user/my-bot",
            restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
        )
        await bot.add_cog(AutoUpgradeCog(bot, config, drain_check=lambda: not active_sessions))

    Args:
        bot: The Discord bot instance.
        config: Upgrade configuration.
        drain_check: Optional callable that returns True when it is safe to restart
            (e.g. no active user sessions). Called repeatedly until True or timeout.
        drain_timeout: Maximum seconds to wait for drain_check to return True.
            After this, the restart proceeds regardless. Default: 300s.
        drain_poll_interval: Seconds between drain_check polls. Default: 10s.
    """

    def __init__(
        self,
        bot: commands.Bot,
        config: UpgradeConfig,
        drain_check: Callable[[], bool] | None = None,
        drain_timeout: int = 300,
        drain_poll_interval: int = 10,
    ) -> None:
        self.bot = bot
        self.config = config
        self._drain_check = drain_check
        self._drain_timeout = drain_timeout
        self._drain_poll_interval = drain_poll_interval
        self._lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle upgrade trigger messages."""
        if not message.webhook_id:
            return

        if (
            self.config.allowed_webhook_ids is not None
            and message.webhook_id not in self.config.allowed_webhook_ids
        ):
            return

        if (
            self.config.channel_ids is not None
            and message.channel.id not in self.config.channel_ids
        ):
            return

        if message.content.strip() != self.config.trigger_prefix:
            return

        logger.info("Auto-upgrade trigger received: %r", self.config.trigger_prefix)

        if self._lock.locked():
            await message.reply("⏳ Upgrade is already running. Skipping.")
            return

        async with self._lock:
            await self._run_upgrade(message)

    async def _run_upgrade(self, trigger_message: discord.Message) -> None:
        """Execute the upgrade pipeline."""
        thread = await trigger_message.create_thread(name=self.config.trigger_prefix[:100])

        try:
            # Step 0: Optional upgrade approval before any subprocess runs
            if self.config.upgrade_approval:
                await self._wait_for_approval(
                    trigger_message,
                    thread,
                    prompt=(
                        f"📦 New release of **{self.config.package_name}** detected. "
                        "React ✅ on this message to start the upgrade."
                    ),
                )

            # Step 1: Upgrade package
            upgrade_cmd = self.config.upgrade_command or [
                "uv",
                "lock",
                "--upgrade-package",
                self.config.package_name,
            ]
            ok = await self._run_step(thread, "upgrade", upgrade_cmd)
            if not ok:
                await trigger_message.add_reaction("❌")
                return

            # Step 2: Sync dependencies
            sync_cmd = self.config.sync_command or ["uv", "sync"]
            ok = await self._run_step(thread, "sync", sync_cmd)
            if not ok:
                await trigger_message.add_reaction("❌")
                return

            # Step 3: Optional restart
            if self.config.restart_command:
                if self.config.restart_approval:
                    await self._wait_for_approval(trigger_message, thread)
                # Snapshot active sessions BEFORE drain so we can resume them after restart.
                active_thread_ids = self._collect_active_thread_ids()
                await self._drain(thread)
                await self._mark_sessions_for_resume(active_thread_ids, thread)
                await self._restart(trigger_message, thread)
            else:
                await trigger_message.add_reaction("✅")
                await thread.send("✅ Upgrade complete (no restart configured).")

        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 — asyncio.TimeoutError != builtins.TimeoutError on Python 3.10
            await thread.send("❌ Step timed out.")
            await trigger_message.add_reaction("❌")
        except Exception:
            logger.exception("Auto-upgrade error")
            await thread.send("❌ Upgrade failed with an unexpected error.")
            await trigger_message.add_reaction("❌")

    def _collect_active_thread_ids(self) -> frozenset[int]:
        """Return the IDs of threads with currently-running Claude sessions.

        Iterates all Cogs looking for ``_active_runners`` dicts (duck-typed to
        avoid a hard import dependency on ``ClaudeChatCog``).  Call this
        *before* :meth:`_drain` so you capture sessions that are mid-run.
        """
        thread_ids: set[int] = set()
        for cog in self.bot.cogs.values():
            if cog is self:
                continue
            active_runners = getattr(cog, "_active_runners", None)
            if isinstance(active_runners, dict):
                thread_ids.update(active_runners.keys())
        return frozenset(thread_ids)

    async def _mark_sessions_for_resume(
        self,
        thread_ids: frozenset[int],
        status_thread: discord.Thread,
    ) -> None:
        """Mark *thread_ids* in the pending-resumes table.

        Called just before the restart command so that Claude sessions which
        were active at upgrade time are automatically resumed on the next bot
        startup.  No-op when ``bot.resume_repo`` is not configured.

        ``session_id`` is auto-resolved from ``bot.session_repo`` when
        available, enabling ``--resume`` continuity.
        """
        if not thread_ids:
            return

        resume_repo = getattr(self.bot, "resume_repo", None)
        if resume_repo is None:
            return

        session_repo = getattr(self.bot, "session_repo", None)
        marked = 0

        for tid in thread_ids:
            try:
                session_id: str | None = None
                if session_repo is not None:
                    record = await session_repo.get(tid)
                    if record is not None:
                        session_id = record.session_id

                await resume_repo.mark(
                    tid,
                    session_id=session_id,
                    reason="bot_upgrade",
                    resume_prompt=(
                        "ボットがパッケージアップグレードのため再起動しました。"
                        "前の作業の続きを確認し、必要な残作業があれば完了してください。"
                    ),
                )
                marked += 1
            except Exception:
                logger.warning("Failed to mark thread %d for resume", tid, exc_info=True)

        if marked:
            await status_thread.send(
                f"📌 {marked} active session(s) marked for auto-resume after restart."
            )

    def _auto_drain_check(self) -> bool:
        """Check all DrainAware Cogs registered on the bot.

        Returns True when every DrainAware Cog has ``active_count == 0``.
        If no DrainAware Cogs are found, returns True (safe to restart).
        """
        return all(
            cog.active_count == 0
            for cog in self.bot.cogs.values()
            if isinstance(cog, DrainAware) and cog is not self
        )

    async def _drain(self, thread: discord.Thread) -> None:
        """Wait until drain_check returns True or drain_timeout elapses.

        If an explicit drain_check was provided, uses that.
        Otherwise, auto-discovers all DrainAware Cogs on the bot.
        Posts status updates to the Discord thread while waiting.
        """
        check = self._drain_check or self._auto_drain_check
        if check():
            return

        await thread.send(
            f"⏳ Upgrade ready — waiting for active sessions to finish "
            f"(max {self._drain_timeout}s)..."
        )
        elapsed = 0
        while elapsed < self._drain_timeout:
            await asyncio.sleep(self._drain_poll_interval)
            elapsed += self._drain_poll_interval
            if check():
                await thread.send(f"✅ Sessions finished ({elapsed}s). Restarting now...")
                return

        await thread.send(f"⚠️ Drain timeout ({self._drain_timeout}s elapsed) — restarting anyway.")

    async def _wait_for_approval(
        self,
        trigger_message: discord.Message,
        thread: discord.Thread,
        *,
        prompt: str | None = None,
    ) -> None:
        """Wait for a user to approve by reacting with ✅.

        Posts a notification with a ✅ reaction. When any non-bot user adds
        the same reaction, approval is granted. Sends periodic reminders
        every ``_drain_timeout`` seconds while waiting.

        Args:
            trigger_message: The original webhook/trigger message.
            thread: The thread to post status messages in.
            prompt: Custom prompt text. Defaults to a restart-approval message.
        """
        text = prompt or "📦 Update installed. React ✅ on this message to restart."
        approval_msg = await thread.send(text)
        await approval_msg.add_reaction("✅")

        while True:
            try:
                event = await self.bot.wait_for(
                    "raw_reaction_add",
                    check=lambda e: (
                        e.message_id == approval_msg.id
                        and str(e.emoji) == "✅"
                        and (self.bot.user is None or e.user_id != self.bot.user.id)
                    ),
                    timeout=float(self._drain_timeout),
                )
                logger.info("Restart approved by user %s", event.user_id)
                await thread.send("👍 Restart approved!")
                return
            except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 — asyncio.TimeoutError != builtins.TimeoutError on Python 3.10
                await thread.send(
                    "⏳ Still waiting for restart approval... React ✅ above when ready."
                )

    async def _restart(
        self,
        trigger_message: discord.Message,
        thread: discord.Thread,
    ) -> None:
        """Execute the restart command (fire-and-forget).

        Uses create_subprocess_exec (not shell=True) — all args are from
        UpgradeConfig, not user input. Safe by construction.
        """
        await thread.send("🔄 Restarting...")
        await trigger_message.add_reaction("✅")
        await asyncio.sleep(1)
        assert self.config.restart_command is not None  # Caller checks this
        await asyncio.create_subprocess_exec(
            *self.config.restart_command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _run_step(
        self,
        thread: discord.Thread,
        step_name: str,
        command: list[str],
    ) -> bool:
        """Run a single subprocess step, posting output to the thread.

        All command args come from UpgradeConfig (server-side config),
        not from user/webhook input. Uses create_subprocess_exec for safety.

        Returns True on success, False on failure.
        """
        cmd_str = " ".join(command)
        await thread.send(f"⚙️ `{cmd_str}`")

        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.config.working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.config.step_timeout)
        output = stdout.decode("utf-8", errors="replace").strip()

        if output:
            # Truncate to fit Discord message limit
            truncated = output[:1800]
            await thread.send(f"```\n{truncated}\n```")

        if proc.returncode != 0:
            await thread.send(f"❌ `{step_name}` failed (exit code {proc.returncode}).")
            return False

        return True
