"""claude-code-discord-bridge — Discord frontend for Claude Code CLI.

Built entirely by Claude Code itself. See README.md for details.

Quick start::

    from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository

"""

from .claude.parser import parse_line
from .claude.runner import ClaudeRunner
from .claude.types import MessageType, StreamEvent, ToolCategory, ToolUseEvent
from .cogs.auto_upgrade import AutoUpgradeCog, UpgradeConfig
from .cogs.claude_chat import ClaudeChatCog
from .cogs.session_manage import SessionManageCog
from .cogs.skill_command import SkillCommandCog
from .cogs.webhook_trigger import WebhookTrigger, WebhookTriggerCog
from .database.notification_repo import NotificationRepository
from .database.repository import SessionRepository
from .discord_ui.chunker import chunk_message
from .discord_ui.embeds import (
    error_embed,
    session_complete_embed,
    session_start_embed,
    tool_use_embed,
)
from .discord_ui.status import StatusManager
from .protocols import DrainAware
from .session_sync import CliSession, SessionMessage, extract_recent_messages, scan_cli_sessions

__all__ = [
    # Core
    "ClaudeRunner",
    "ClaudeChatCog",
    "SessionManageCog",
    "SkillCommandCog",
    "SessionRepository",
    # Session Sync
    "CliSession",
    "SessionMessage",
    "extract_recent_messages",
    "scan_cli_sessions",
    # Webhook & Automation
    "WebhookTriggerCog",
    "WebhookTrigger",
    "AutoUpgradeCog",
    "UpgradeConfig",
    "DrainAware",
    "NotificationRepository",
    # Types
    "MessageType",
    "StreamEvent",
    "ToolCategory",
    "ToolUseEvent",
    # Parsing
    "parse_line",
    # UI
    "StatusManager",
    "chunk_message",
    "error_embed",
    "session_complete_embed",
    "session_start_embed",
    "tool_use_embed",
]
