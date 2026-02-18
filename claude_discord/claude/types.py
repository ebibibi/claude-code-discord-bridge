"""Type definitions for Claude Code CLI stream-json output."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import discord


class MessageType(Enum):
    """Top-level message types in stream-json output."""

    SYSTEM = "system"
    ASSISTANT = "assistant"
    USER = "user"
    RESULT = "result"


class ContentBlockType(Enum):
    """Content block types within assistant messages."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"


class ToolCategory(Enum):
    """Categories for tool use, used for status emoji selection."""

    READ = "read"
    EDIT = "edit"
    COMMAND = "command"
    WEB = "web"
    THINK = "think"
    OTHER = "other"


# Map tool names to categories
TOOL_CATEGORIES: dict[str, ToolCategory] = {
    "Read": ToolCategory.READ,
    "Glob": ToolCategory.READ,
    "Grep": ToolCategory.READ,
    "LS": ToolCategory.READ,
    "Write": ToolCategory.EDIT,
    "Edit": ToolCategory.EDIT,
    "NotebookEdit": ToolCategory.EDIT,
    "Bash": ToolCategory.COMMAND,
    "WebFetch": ToolCategory.WEB,
    "WebSearch": ToolCategory.WEB,
    "Task": ToolCategory.OTHER,
}


@dataclass
class ToolUseEvent:
    """Parsed tool use event from stream-json."""

    tool_id: str
    tool_name: str
    tool_input: dict[str, Any]
    category: ToolCategory

    @property
    def display_name(self) -> str:
        """Human-readable description of what this tool is doing."""
        name = self.tool_name
        inp = self.tool_input

        if name == "Read":
            return f"Reading: {inp.get('file_path', 'unknown')}"
        if name == "Write":
            return f"Writing: {inp.get('file_path', 'unknown')}"
        if name == "Edit":
            return f"Editing: {inp.get('file_path', 'unknown')}"
        if name in ("Glob", "Grep"):
            pattern = inp.get("pattern", inp.get("glob", ""))
            return f"Searching: {pattern}"
        if name == "Bash":
            cmd = inp.get("command", "")
            # Truncate long commands
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            return f"Running: {cmd}"
        if name == "WebSearch":
            return f"Searching web: {inp.get('query', '')}"
        if name == "WebFetch":
            return f"Fetching: {inp.get('url', '')}"
        if name == "Task":
            return f"Spawning agent: {inp.get('description', '')}"
        return f"Using: {name}"


@dataclass
class StreamEvent:
    """A parsed event from the Claude Code stream-json output."""

    message_type: MessageType
    raw: dict = field(default_factory=dict)
    session_id: str | None = None
    text: str | None = None
    tool_use: ToolUseEvent | None = None
    tool_result_id: str | None = None
    tool_result_content: str | None = None
    thinking: str | None = None
    is_complete: bool = False
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None


@dataclass
class SessionState:
    """Tracks the state of a Claude Code session during a single run.

    active_tools maps tool_use_id -> Discord Message, enabling Phase 2
    live embed updates when tool results arrive.
    """

    session_id: str | None = None
    thread_id: int = 0
    accumulated_text: str = ""
    active_tools: dict[str, discord.Message] = field(default_factory=dict)
