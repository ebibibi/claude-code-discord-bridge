"""Type definitions for Claude Code CLI stream-json output.

This module re-exports all frontend-agnostic types from claude_code_core
and adds the Discord-specific SessionState dataclass.

Backward-compatible: all existing imports from this path continue to work.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from claude_code_core.frontend import ActivityHandle

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

    active_tools maps tool_use_id -> frontend-neutral ActivityHandle, enabling
    the originating surface to render and finish work in its native UI.
    """

    session_id: str | None = None
    thread_id: int = 0
    accumulated_text: str = ""
    partial_text: str = ""
    # jump_url of the last directly-posted assistant text message (inbox linking)
    last_assistant_url: str | None = None
    active_tools: dict[str, ActivityHandle] = field(default_factory=dict)
    # Kept for one compatibility release; timers now belong inside a surface's
    # ActivityHandle rather than in the frontend-neutral processor.
    active_timers: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    # TodoWrite: frontend-owned live activity.
    todo_message: ActivityHandle | None = None
    # Number of tool calls dispatched this session (used to detect significant work)
    tool_use_count: int = 0
