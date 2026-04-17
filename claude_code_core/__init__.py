"""claude-code-core: Frontend-agnostic core library for Claude Code CLI integration.

This package provides the essential building blocks for any application
that needs to invoke the Claude Code CLI and process its stream-json output:

- **ClaudeRunner**: Async subprocess manager for the Claude Code CLI
- **StreamEvent / parse_line**: Stream-json parser and typed event model
- **SessionRepository**: SQLite-backed session persistence
- **rewind utilities**: JSONL session history manipulation

Usage::

    from claude_code_core import ClaudeRunner, StreamEvent, SessionRepository, init_db

    # Initialize the database
    await init_db("sessions.db")

    # Create a runner and stream events
    runner = ClaudeRunner(model="sonnet")
    async for event in runner.run("Hello, Claude!"):
        if event.text:
            print(event.text)
"""

from __future__ import annotations

# Database
from .lounge_repo import LoungeMessage, LoungeRepository
from .models import init_db

# Parser
from .parser import parse_line

# Rewind
from .rewind import TurnEntry, find_session_jsonl, parse_user_turns, truncate_jsonl_at_line

# Runner
from .runner import ClaudeRunner
from .session_repo import SessionRecord, SessionRepository, UsageStatsRepository

# Types (all frontend-agnostic types)
from .types import (
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
    # Types
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
    # Parser
    "parse_line",
    # Runner
    "ClaudeRunner",
    # Database
    "LoungeMessage",
    "LoungeRepository",
    "SessionRecord",
    "SessionRepository",
    "UsageStatsRepository",
    "init_db",
    # Rewind
    "TurnEntry",
    "find_session_jsonl",
    "parse_user_turns",
    "truncate_jsonl_at_line",
]
