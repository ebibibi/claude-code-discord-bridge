"""Entry point for claude-code-discord-bridge bot.

Standalone launcher that uses ``setup_bridge()`` for full Cog auto-setup
and optionally loads custom Cogs from an external directory via
``CUSTOM_COGS_DIR`` env or ``--cogs-dir`` CLI flag.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from claude_code_core.backend import create_backend

from .bot import ClaudeDiscordBot
from .cog_loader import load_custom_cogs
from .setup import setup_bridge
from .utils.logger import setup_logging

logger = logging.getLogger(__name__)


def load_config() -> dict[str, str]:
    """Load and validate configuration from environment."""
    load_dotenv(find_dotenv(usecwd=True))

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        logger.error("DISCORD_BOT_TOKEN is required")
        sys.exit(1)

    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
    if not channel_id:
        logger.error("DISCORD_CHANNEL_ID is required")
        sys.exit(1)

    def _env(new: str, old: str, default: str = "") -> str:
        """Read CCDB_* env var with CLAUDE_* fallback."""
        return os.getenv(new) or os.getenv(old, default)

    return {
        "token": token,
        "channel_id": channel_id,
        "backend": os.getenv("CCDB_BACKEND", "claude"),
        "command": _env("CCDB_COMMAND", "CLAUDE_COMMAND", ""),
        # Per-backend explicit command paths. Used by BackendFactory when
        # the user switches backend at runtime via /backend.
        "claude_command": _env("CCDB_CLAUDE_COMMAND", "CLAUDE_COMMAND", ""),
        "codex_command": os.getenv("CCDB_CODEX_COMMAND", ""),
        "model": _env("CCDB_MODEL", "CLAUDE_MODEL", "sonnet"),
        "permission_mode": _env("CCDB_PERMISSION_MODE", "CLAUDE_PERMISSION_MODE", "acceptEdits"),
        "working_dir": _env("CCDB_WORKING_DIR", "CLAUDE_WORKING_DIR", ""),
        "dangerously_skip_permissions": _env(
            "CCDB_DANGEROUSLY_SKIP_PERMISSIONS", "CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS", ""
        ),
        "allowed_tools": _env("CCDB_ALLOWED_TOOLS", "CLAUDE_ALLOWED_TOOLS", ""),
        "effort": _env("CCDB_EFFORT", "CLAUDE_EFFORT", ""),
        "append_system_prompt": os.getenv("APPEND_SYSTEM_PROMPT", ""),
        "max_concurrent": os.getenv("MAX_CONCURRENT_SESSIONS", "3"),
        "timeout": os.getenv("SESSION_TIMEOUT_SECONDS", "300"),
        "owner_id": os.getenv("DISCORD_OWNER_ID", ""),
        "channel_ids": _env("CCDB_CHANNEL_IDS", "CLAUDE_CHANNEL_IDS", ""),
        "monitor_all_channels": _env(
            "CCDB_MONITOR_ALL_CHANNELS", "CLAUDE_MONITOR_ALL_CHANNELS", "false"
        ),
        "api_host": os.getenv("API_HOST", "127.0.0.1"),
        "api_port": os.getenv("API_PORT", ""),
        "custom_cogs_dir": os.getenv("CUSTOM_COGS_DIR", ""),
        "cli_sessions_path": os.getenv("CLI_SESSIONS_PATH", ""),
        "thread_inbox_enabled": os.getenv("THREAD_INBOX_ENABLED", "false"),
    }


async def main() -> None:
    """Start the bot."""
    setup_logging()
    config = load_config()

    channel_id = int(config["channel_id"])

    # Parse optional multi-channel IDs
    claude_channel_ids: set[int] | None = None
    if config["channel_ids"]:
        claude_channel_ids = {
            int(x.strip()) for x in config["channel_ids"].split(",") if x.strip().isdigit()
        } or None

    # Parse allowed tools
    allowed_tools: list[str] | None = None
    if config["allowed_tools"]:
        allowed_tools = [t.strip() for t in config["allowed_tools"].split(",") if t.strip()] or None

    # Create runner via backend factory (CCDB_BACKEND=claude|codex)
    backend_name = config["backend"]
    default_command = "codex" if backend_name == "codex" else "claude"

    # BackendFactory is the runtime authority for building Claude/Codex
    # runners on demand (e.g. when the user switches via /backend).
    from .backend_factory import BackendFactory

    factory = BackendFactory(
        claude_command=config["claude_command"]
        or (config["command"] if backend_name == "claude" else "")
        or "claude",
        codex_command=config["codex_command"]
        or (config["command"] if backend_name == "codex" else "")
        or "codex",
        permission_mode=config["permission_mode"],
        working_dir=config["working_dir"] or None,
        timeout_seconds=int(config["timeout"]),
        dangerously_skip_permissions=config["dangerously_skip_permissions"].lower()
        in ("true", "1", "yes"),
        allowed_tools=allowed_tools,
        append_system_prompt=config["append_system_prompt"] or None,
        effort=config["effort"] or None,
    )

    runner = create_backend(
        backend=backend_name,
        command=config["command"] or default_command,
        model=config["model"],
        permission_mode=config["permission_mode"],
        working_dir=config["working_dir"] or None,
        timeout_seconds=int(config["timeout"]),
        dangerously_skip_permissions=config["dangerously_skip_permissions"].lower()
        in ("true", "1", "yes"),
        allowed_tools=allowed_tools,
        append_system_prompt=config["append_system_prompt"] or None,
        effort=config["effort"] or None,
    )

    owner_id = int(config["owner_id"]) if config["owner_id"] else None
    bot = ClaudeDiscordBot(
        channel_id=channel_id,
        owner_id=owner_id,
    )

    # Optional API server
    api_server = None
    if config["api_port"]:
        from .database.notification_repo import NotificationRepository
        from .ext.api_server import ApiServer

        notification_repo = NotificationRepository("data/notifications.db")
        await notification_repo.init_db()
        api_server = ApiServer(
            repo=notification_repo,
            bot=bot,
            default_channel_id=channel_id,
            host=config["api_host"],
            port=int(config["api_port"]),
        )

    async with bot:
        # Full Cog auto-setup via setup_bridge
        allowed_user_ids = {owner_id} if owner_id else None
        components = await setup_bridge(
            bot,
            runner,
            api_server=api_server,
            backend_factory=factory,
            allowed_user_ids=allowed_user_ids,
            claude_channel_id=channel_id,
            claude_channel_ids=claude_channel_ids,
            cli_sessions_path=config["cli_sessions_path"] or None,
            enable_thread_inbox=config["thread_inbox_enabled"].lower() == "true",
            monitor_all_channels=config["monitor_all_channels"].lower() in ("true", "1", "yes"),
        )

        # Load custom Cogs from external directory
        cogs_dir = config["custom_cogs_dir"]
        if cogs_dir:
            await load_custom_cogs(Path(cogs_dir), bot, runner, components)

        # Cleanup old sessions on startup
        deleted = await components.session_repo.cleanup_old(days=30)
        if deleted:
            logger.info("Cleaned up %d old sessions", deleted)

        # Start API server if configured
        if api_server is not None:
            await api_server.start()

        # Handle signals (add_signal_handler is not supported on Windows)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))

        await bot.start(config["token"])


if __name__ == "__main__":
    asyncio.run(main())
