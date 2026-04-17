"""Type definitions for Claude Code CLI stream-json output.

This module re-exports all frontend-agnostic types from claude_code_core
and adds the Discord-specific SessionState dataclass.

Backward-compatible: all existing imports from this path continue to work.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Re-export everything from core
from claude_code_core.types import (
    TOOL_CATEGORIES,
    AskOption,
    AskQuestion,
    ContentBlockType,
    ElicitationRequest,
    ImageData,
    MessageType,
    PermissionRequest,
    RateLimitInfo,
    StreamEvent,
    TodoItem,
    ToolCategory,
    ToolUseEvent,
)

if TYPE_CHECKING:
    import discord

__all__ = [
    # Re-exported from core
    "AskOption",
    "AskQuestion",
    "ContentBlockType",
    "ElicitationRequest",
    "ImageData",
    "MessageType",
    "PermissionRequest",
    "RateLimitInfo",
    "StreamEvent",
    "TOOL_CATEGORIES",
    "TodoItem",
    "ToolCategory",
    "ToolUseEvent",
    # Discord-specific
    "SessionState",
]


@dataclass
class SessionState:
    """Tracks the state of a Claude Code session during a single run.

    active_tools maps tool_use_id -> Discord Message, enabling live embed
    updates when tool results arrive.

    active_timers maps tool_use_id -> asyncio.Task that periodically edits
    the in-progress embed to show elapsed execution time. Cancelled on result.
    """

    session_id: str | None = None
    thread_id: int = 0
    accumulated_text: str = ""
    partial_text: str = ""
    active_tools: dict[str, discord.Message] = field(default_factory=dict)
    active_timers: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    # TodoWrite: reference to the live todo embed message (edited in-place on each update)
    todo_message: discord.Message | None = None
    # Number of tool calls dispatched this session (used to detect significant work)
    tool_use_count: int = 0
