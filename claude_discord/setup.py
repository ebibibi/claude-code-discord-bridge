"""One-call setup for all ccdb bridge Cogs.

Consumers call this instead of manually wiring each Cog.
New Cogs added to ccdb are automatically included — no consumer code changes needed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext.commands import Bot

    from .claude.runner import ClaudeRunner
    from .database.lounge_repo import LoungeRepository
    from .database.repository import SessionRepository
    from .database.resume_repo import PendingResumeRepository
    from .database.task_repo import TaskRepository
    from .ext.api_server import ApiServer

logger = logging.getLogger(__name__)


@dataclass
class BridgeComponents:
    """References to initialized bridge components.

    After calling setup_bridge(), pass this to apply_to_api_server() so the
    ApiServer gains access to all repos without manual wiring::

        components = await setup_bridge(bot, runner, api_server=api_server)

    Or manually if you need more control::

        components = await setup_bridge(bot, runner)
        components.apply_to_api_server(api_server)
    """

    session_repo: SessionRepository
    task_repo: TaskRepository | None = None
    lounge_repo: LoungeRepository | None = None
    resume_repo: PendingResumeRepository | None = None

    def apply_to_api_server(self, api_server: ApiServer) -> None:
        """Wire all optional repos to an ApiServer instance.

        Idempotent — safe to call multiple times.  Only non-None repos are
        applied, so repos that are disabled (e.g. scheduler off) are left as-is.

        When a new repo is added to BridgeComponents in the future, add it here
        and consumers automatically pick it up without changing their own code.
        """
        if self.task_repo is not None:
            api_server.task_repo = self.task_repo
        if self.lounge_repo is not None:
            api_server.lounge_repo = self.lounge_repo
        if self.resume_repo is not None:
            api_server.resume_repo = self.resume_repo
        api_server.session_repo = self.session_repo


async def setup_bridge(
    bot: Bot,
    runner: ClaudeRunner,
    *,
    api_server: ApiServer | None = None,
    session_db_path: str = "data/sessions.db",
    allowed_user_ids: set[int] | None = None,
    claude_channel_id: int | None = None,
    cli_sessions_path: str | None = None,
    enable_scheduler: bool = True,
    task_db_path: str = "data/tasks.db",
    lounge_channel_id: int | None = None,
    worktree_base_dir: str | None = None,
) -> BridgeComponents:
    """Initialize and register all ccdb Cogs in one call.

    This is the recommended way for consumers to set up ccdb.
    New Cogs added to ccdb will be automatically included.

    Pass ``api_server`` to automatically wire all repos and set the runner's
    ``api_port`` — consumers then need zero manual wiring::

        components = await setup_bridge(bot, runner, api_server=api_server, ...)
        # Done — no manual repo wiring needed.

    Args:
        bot: Discord bot instance.
        runner: ClaudeRunner for Claude CLI invocation.
        api_server: Optional ApiServer to auto-wire repos into.  Also sets
                    runner.api_port so CCDB_API_URL is available to Claude.
        session_db_path: Path for session SQLite DB.
        allowed_user_ids: Set of Discord user IDs allowed to use Claude.
        claude_channel_id: Channel ID for Claude chat (needed for SkillCommandCog).
        cli_sessions_path: Path to ~/.claude/projects for session sync.
        enable_scheduler: Whether to enable SchedulerCog.
        task_db_path: Path for scheduled tasks SQLite DB.
        lounge_channel_id: Discord channel ID for AI Lounge messages.
                           Defaults to COORDINATION_CHANNEL_ID env var so
                           lounge and coordination share the same channel
                           with no extra configuration needed.
        worktree_base_dir: Base directory to scan for session worktrees
                           (e.g. ``/home/user``). When set, a WorktreeManager
                           is created and attached to the bot, enabling automatic
                           cleanup of session worktrees at session end and startup.
                           Defaults to WORKTREE_BASE_DIR env var, or None (disabled).

    Returns:
        BridgeComponents with references to initialized repositories.
    """
    from .cogs.claude_chat import ClaudeChatCog
    from .cogs.scheduler import SchedulerCog
    from .cogs.session_manage import SessionManageCog
    from .cogs.skill_command import SkillCommandCog
    from .database.ask_repo import PendingAskRepository
    from .database.lounge_repo import LoungeRepository
    from .database.models import init_db
    from .database.repository import SessionRepository
    from .database.resume_repo import PendingResumeRepository
    from .database.settings_repo import SettingsRepository
    from .database.task_repo import TaskRepository
    from .worktree import WorktreeManager

    # Lounge shares the coordination channel unless explicitly overridden
    if lounge_channel_id is None:
        ch_str = os.getenv("COORDINATION_CHANNEL_ID", "")
        lounge_channel_id = int(ch_str) if ch_str.isdigit() else None

    # WorktreeManager — attach to bot so cogs can access it via bot.worktree_manager
    if worktree_base_dir is None:
        worktree_base_dir = os.getenv("WORKTREE_BASE_DIR")
    if worktree_base_dir is not None:
        if not hasattr(bot, "worktree_manager"):
            bot.worktree_manager = WorktreeManager(base_dir=worktree_base_dir)  # type: ignore[attr-defined]
        logger.info("WorktreeManager enabled (base_dir=%s)", worktree_base_dir)

    # --- Session DB (also hosts lounge_messages and pending_resumes tables) ---
    os.makedirs(os.path.dirname(session_db_path) or ".", exist_ok=True)
    await init_db(session_db_path)
    session_repo = SessionRepository(session_db_path)
    settings_repo = SettingsRepository(session_db_path)
    ask_repo = PendingAskRepository(session_db_path)
    lounge_repo = LoungeRepository(session_db_path)
    resume_repo = PendingResumeRepository(session_db_path)
    logger.info("Session DB initialized: %s", session_db_path)

    # Attach repos to bot so generic cogs (e.g. AutoUpgradeCog) can discover them
    # without a hard import dependency on ccdb internals.
    bot.session_repo = session_repo  # type: ignore[attr-defined]
    bot.resume_repo = resume_repo  # type: ignore[attr-defined]

    # --- ClaudeChatCog ---
    chat_cog = ClaudeChatCog(
        bot,  # type: ignore[arg-type]  # consumers pass their own Bot subclass
        repo=session_repo,
        runner=runner,
        allowed_user_ids=allowed_user_ids,
        ask_repo=ask_repo,
        lounge_repo=lounge_repo,
        resume_repo=resume_repo,
        settings_repo=settings_repo,
    )
    await bot.add_cog(chat_cog)
    logger.info("Registered ClaudeChatCog")

    # --- SessionManageCog ---
    session_manage_cog = SessionManageCog(
        bot,  # type: ignore[arg-type]  # consumers pass their own Bot subclass
        repo=session_repo,
        cli_sessions_path=cli_sessions_path,
        settings_repo=settings_repo,
    )
    await bot.add_cog(session_manage_cog)
    logger.info("Registered SessionManageCog")

    # --- SkillCommandCog (requires channel ID) ---
    if claude_channel_id is not None:
        skill_cog = SkillCommandCog(
            bot,
            repo=session_repo,
            runner=runner,
            claude_channel_id=claude_channel_id,
            allowed_user_ids=allowed_user_ids,
        )
        await bot.add_cog(skill_cog)
        logger.info("Registered SkillCommandCog")

    # --- SchedulerCog (optional) ---
    task_repo: TaskRepository | None = None
    if enable_scheduler:
        os.makedirs(os.path.dirname(task_db_path) or ".", exist_ok=True)
        task_repo = TaskRepository(task_db_path)
        await task_repo.init_db()
        scheduler_cog = SchedulerCog(bot, runner, repo=task_repo)
        await bot.add_cog(scheduler_cog)
        logger.info("Registered SchedulerCog")

    components = BridgeComponents(
        session_repo=session_repo,
        task_repo=task_repo,
        lounge_repo=lounge_repo,
        resume_repo=resume_repo,
    )

    # Auto-wire repos to ApiServer and set runner.api_port if provided
    if api_server is not None:
        components.apply_to_api_server(api_server)
        if runner.api_port is None:
            runner.api_port = api_server.port
        logger.info("Auto-wired repos to ApiServer (port=%d)", api_server.port)

    return components
