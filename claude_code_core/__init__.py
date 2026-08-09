"""claude-code-core: Frontend-agnostic core library for Claude Code CLI integration.

This package provides the essential building blocks for any application
that needs to invoke the Claude Code CLI and process its stream-json output:

- **ClaudeRunner**: Async subprocess manager for the Claude Code CLI
- **StreamEvent / parse_line**: Stream-json parser and typed event model
- **SessionRepository**: SQLite-backed session persistence
- **rewind utilities**: JSONL session history manipulation
- **frontend protocol**: the vocabulary a chat frontend (Discord, Teams, ...)
  implements so the session machinery never names a platform
- **rendering**: capability-driven table rendering and message chunking, shared
  by every frontend
- **conformance**: the contract a frontend must satisfy, importable so anyone
  building one can check their own implementation

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

# API provider detection
from .api_provider import detect_api_provider

# Backend
from .backend import SessionBackend, create_backend
from .codex_runner import CodexRunner, parse_codex_line

# Database
# Frontend protocol
from .conformance import ConformanceReport, check_surface
from .frontend import (
    ActivityHandle,
    ActivitySpec,
    Choice,
    ChoicePrompt,
    ConversationSurface,
    FormField,
    FormPrompt,
    InboundAttachment,
    InboundMessage,
    InterruptHandle,
    Mention,
    Notice,
    NoticeLevel,
    OutboundFile,
    SessionFrontend,
    StatusKind,
    SurfaceCapabilities,
    TextStream,
    ThreadKey,
    derive_thread_key,
)
from .memory_surface import MemorySurface

# Parser
from .parser import parse_line

# Rendering
from .rendering import chunk_message, render_for, render_table, wrap_tables_in_fences

# Rewind
from .rewind import TurnEntry, find_session_jsonl, parse_user_turns, truncate_jsonl_at_line

# Runner
from .runner import ClaudeRunner

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
    # Rendering
    "chunk_message",
    "render_for",
    "render_table",
    "wrap_tables_in_fences",
    # API provider
    "detect_api_provider",
    # Backend
    "CodexRunner",
    "SessionBackend",
    "create_backend",
    "parse_codex_line",
    # Runner
    "ClaudeRunner",
    # Database
    "LoungeMessage",
    "LoungeRepository",
    "SessionRecord",
    "SessionRepository",
    "UsageStatsRepository",
    "init_db",
    # Frontend protocol
    "ActivityHandle",
    "ConformanceReport",
    "MemorySurface",
    "check_surface",
    "ActivitySpec",
    "Choice",
    "ChoicePrompt",
    "ConversationSurface",
    "FormField",
    "FormPrompt",
    "InboundAttachment",
    "InboundMessage",
    "InterruptHandle",
    "Mention",
    "Notice",
    "NoticeLevel",
    "OutboundFile",
    "SessionFrontend",
    "StatusKind",
    "SurfaceCapabilities",
    "TextStream",
    "ThreadKey",
    "derive_thread_key",
    # Rewind
    "TurnEntry",
    "find_session_jsonl",
    "parse_user_turns",
    "truncate_jsonl_at_line",
]


# ---------------------------------------------------------------------------
# Lazily imported members
# ---------------------------------------------------------------------------
#
# The database-backed repositories need ``aiosqlite``. Importing them here
# meant that ``claude_code_core.frontend`` — a module of protocols and value
# objects with no storage in it — could not be imported without a database
# driver installed. That is not a theoretical tidiness point: the Teams relay
# receiver runs on a public machine deliberately built with nothing but an HTTP
# server and a JWT library, and it fell over on `import aiosqlite` at startup.
#
# PEP 562: these resolve on first attribute access, so
# ``from claude_code_core import SessionRepository`` still works exactly as
# before, and ``from claude_code_core.frontend import ...`` no longer drags a
# storage layer in behind it.
_LAZY: dict[str, str] = {
    "LoungeMessage": ".lounge_repo",
    "LoungeRepository": ".lounge_repo",
    "init_db": ".models",
    "SessionRecord": ".session_repo",
    "SessionRepository": ".session_repo",
    "UsageStatsRepository": ".session_repo",
}


def __getattr__(name: str):  # noqa: ANN202 — module-level PEP 562 hook
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))
