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
    from .database.task_repo import TaskRepository

logger = logging.getLogger(__name__)


@dataclass
class BridgeComponents:
    """References to initialized bridge components."""

    session_repo: SessionRepository
    task_repo: TaskRepository | None = None
    lounge_repo: LoungeRepository | None = None


async def setup_bridge(
    bot: Bot,
    runner: ClaudeRunner,
    *,
    session_db_path: str = "data/sessions.db",
    allowed_user_ids: set[int] | None = None,
    claude_channel_id: int | None = None,
    cli_sessions_path: str | None = None,
    enable_scheduler: bool = True,
    task_db_path: str = "data/tasks.db",
    lounge_channel_id: int | None = None,
) -> BridgeComponents:
    """Initialize and register all ccdb Cogs in one call.

    This is the recommended way for consumers to set up ccdb.
    New Cogs added to ccdb will be automatically included.

    Args:
        bot: Discord bot instance.
        runner: ClaudeRunner for Claude CLI invocation.
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
    from .database.settings_repo import SettingsRepository
    from .database.task_repo import TaskRepository

    # Lounge shares the coordination channel unless explicitly overridden
    if lounge_channel_id is None:
        ch_str = os.getenv("COORDINATION_CHANNEL_ID", "")
        lounge_channel_id = int(ch_str) if ch_str.isdigit() else None

    # --- Session DB (also hosts lounge_messages table) ---
    os.makedirs(os.path.dirname(session_db_path) or ".", exist_ok=True)
    await init_db(session_db_path)
    session_repo = SessionRepository(session_db_path)
    settings_repo = SettingsRepository(session_db_path)
    ask_repo = PendingAskRepository(session_db_path)
    lounge_repo = LoungeRepository(session_db_path)
    logger.info("Session DB initialized: %s", session_db_path)

    # --- ClaudeChatCog ---
    chat_cog = ClaudeChatCog(
        bot,  # type: ignore[arg-type]  # consumers pass their own Bot subclass
        repo=session_repo,
        runner=runner,
        allowed_user_ids=allowed_user_ids,
        ask_repo=ask_repo,
        lounge_repo=lounge_repo,
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

    return BridgeComponents(
        session_repo=session_repo,
        task_repo=task_repo,
        lounge_repo=lounge_repo,
    )
