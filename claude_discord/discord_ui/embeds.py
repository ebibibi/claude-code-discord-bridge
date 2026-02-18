"""Discord embed builders for Claude Code events."""

from __future__ import annotations

import discord

from ..claude.types import ToolCategory, ToolUseEvent

# Colors
COLOR_INFO = 0x5865F2  # Discord blurple
COLOR_SUCCESS = 0x57F287  # Green
COLOR_ERROR = 0xED4245  # Red
COLOR_TOOL = 0xFEE75C  # Yellow
COLOR_THINKING = 0x9B59B6  # Purple


CATEGORY_ICON: dict[ToolCategory, str] = {
    ToolCategory.READ: "\U0001f4d6",  # 📖
    ToolCategory.EDIT: "\u270f\ufe0f",  # ✏️
    ToolCategory.COMMAND: "\U0001f527",  # 🔧
    ToolCategory.WEB: "\U0001f310",  # 🌐
    ToolCategory.THINK: "\U0001f4ad",  # 💭
    ToolCategory.OTHER: "\U0001f916",  # 🤖
}


def tool_use_embed(tool: ToolUseEvent, in_progress: bool = True) -> discord.Embed:
    """Create an embed for a tool use event."""
    icon = CATEGORY_ICON.get(tool.category, "\U0001f916")
    status = "..." if in_progress else ""
    title = f"{icon} {tool.display_name}{status}"

    embed = discord.Embed(
        title=title[:256],
        color=COLOR_TOOL if in_progress else COLOR_INFO,
    )
    return embed


def session_start_embed(session_id: str | None = None) -> discord.Embed:
    """Create an embed for session start."""
    embed = discord.Embed(
        title="\U0001f916 Claude Code session started",
        color=COLOR_INFO,
    )
    if session_id:
        embed.set_footer(text=f"Session: {session_id[:8]}...")
    return embed


def session_complete_embed(
    cost_usd: float | None = None,
    duration_ms: int | None = None,
) -> discord.Embed:
    """Create an embed for session completion."""
    parts: list[str] = []
    if duration_ms is not None:
        seconds = duration_ms / 1000
        parts.append(f"\u23f1\ufe0f {seconds:.1f}s")
    if cost_usd is not None:
        parts.append(f"\U0001f4b0 ${cost_usd:.4f}")

    description = " | ".join(parts) if parts else None

    return discord.Embed(
        title="\u2705 Done",
        description=description,
        color=COLOR_SUCCESS,
    )


def error_embed(error: str) -> discord.Embed:
    """Create an embed for errors."""
    return discord.Embed(
        title="\u274c Error",
        description=error[:4000],
        color=COLOR_ERROR,
    )
