"""claude-discord — Discord frontend for Claude Code CLI.

Built entirely by Claude Code itself. See README.md for details.

Quick start::

    from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository

"""

from .claude.parser import parse_line
from .claude.runner import ClaudeRunner
from .claude.types import MessageType, StreamEvent, ToolCategory, ToolUseEvent
from .cogs.claude_chat import ClaudeChatCog
from .cogs.skill_command import SkillCommandCog
from .database.repository import SessionRepository
from .discord_ui.chunker import chunk_message
from .discord_ui.embeds import (
    error_embed,
    session_complete_embed,
    session_start_embed,
    tool_use_embed,
)
from .discord_ui.status import StatusManager

__all__ = [
    # Core
    "ClaudeRunner",
    "ClaudeChatCog",
    "SkillCommandCog",
    "SessionRepository",
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
