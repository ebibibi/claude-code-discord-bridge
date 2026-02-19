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
COLOR_ASK = 0x3498DB  # Blue — question-like


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
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
) -> discord.Embed:
    """Create an embed for session completion."""
    parts: list[str] = []
    if duration_ms is not None:
        seconds = duration_ms / 1000
        parts.append(f"\u23f1\ufe0f {seconds:.1f}s")
    if cost_usd is not None:
        parts.append(f"\U0001f4b0 ${cost_usd:.4f}")
    if input_tokens is not None and output_tokens is not None:

        def _fmt(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)

        token_str = f"\U0001f4ca {_fmt(input_tokens)}\u2191 {_fmt(output_tokens)}\u2193"
        if cache_read_tokens:
            total = input_tokens + cache_read_tokens
            hit_pct = int(cache_read_tokens / total * 100) if total else 0
            token_str += f" ({hit_pct}% cache)"
        parts.append(token_str)

    description = " | ".join(parts) if parts else None

    return discord.Embed(
        title="\u2705 Done",
        description=description,
        color=COLOR_SUCCESS,
    )


def tool_result_embed(tool_title: str, result_content: str) -> discord.Embed:
    """Create an embed for a completed tool with its result.

    Replaces the in-progress tool embed once the result is available.
    """
    # Strip the trailing "..." from in-progress title
    title = tool_title.rstrip(".")
    embed = discord.Embed(
        title=title[:256],
        color=COLOR_INFO,
    )
    if result_content:
        # Use a spoiler-style collapsible look via a field
        display = result_content[:1024]
        embed.add_field(name="Result", value=f"```\n{display}\n```", inline=False)
    return embed


def thinking_embed(thinking_text: str) -> discord.Embed:
    """Create an embed for extended thinking content.

    Uses a plain code block (no spoiler) so the text is always rendered with
    Discord's own code block background/foreground — guaranteed readable in
    both dark and light themes regardless of the embed accent color.

    Note: spoiler + code block combinations (||```text```||) do not apply code
    block styling when revealed inside embed descriptions; the text still picks
    up the embed accent color and can become unreadable.
    """
    # Reserve chars for code block markers: ```\n...\n``` = 8 chars overhead
    max_text = 4096 - 8 - len("\n... (truncated)")
    truncated = thinking_text[:max_text]
    if len(thinking_text) > max_text:
        truncated += "\n... (truncated)"
    return discord.Embed(
        title="\U0001f4ad Thinking",
        description=f"```\n{truncated}\n```",
        color=COLOR_THINKING,
    )


def redacted_thinking_embed() -> discord.Embed:
    """Create a placeholder embed for a redacted_thinking block."""
    return discord.Embed(
        title="\U0001f512 Thinking (redacted)",
        description="Some reasoning was performed but cannot be shown.",
        color=0x95A5A6,  # Muted grey
    )


def error_embed(error: str) -> discord.Embed:
    """Create an embed for errors."""
    return discord.Embed(
        title="\u274c Error",
        description=error[:4000],
        color=COLOR_ERROR,
    )


def timeout_embed(seconds: int) -> discord.Embed:
    """Create an embed for session timeout with actionable guidance."""
    return discord.Embed(
        title="\u23f1\ufe0f Session timed out",
        description=(
            f"No response received for {seconds} seconds.\n\n"
            "**What to do:**\n"
            "\u2022 Send a message to resume the session\n"
            "\u2022 Use `/clear` to start fresh"
        ),
        color=COLOR_ERROR,
    )


def ask_embed(question: str, header: str = "") -> discord.Embed:
    """Create an embed for an AskUserQuestion interactive prompt."""
    title = f"❓ {header}" if header else "❓ Claude needs your input"
    return discord.Embed(
        title=title[:256],
        description=question[:4096],
        color=COLOR_ASK,
    )


def stopped_embed() -> discord.Embed:
    """Create an embed for a manually stopped session."""
    return discord.Embed(
        title="\u23f9\ufe0f Session stopped",
        description=(
            "The session was stopped.\n\n"
            "The session is preserved \u2014 send a message to resume, "
            "or use `/clear` to start fresh."
        ),
        color=0xFFA500,  # Orange — not an error, just interrupted
    )


COLOR_RELAY = 0x00BCD4  # Cyan — distinct from info/success/error


def relay_sent_embed(target: discord.Thread, message: str) -> discord.Embed:
    """Confirmation embed posted in the source thread after a relay."""
    preview = message[:200] + ("…" if len(message) > 200 else "")
    embed = discord.Embed(
        title="\U0001f4e4 Relayed",
        description=f"Message sent to {target.mention}\n\n> {preview}",
        color=COLOR_RELAY,
    )
    embed.add_field(name="Jump", value=f"[Go to {target.name}]({target.jump_url})", inline=False)
    return embed


def relay_received_embed(source: discord.Thread, message: str) -> discord.Embed:
    """Attribution embed posted in the target thread when a relay arrives."""
    preview = message[:200] + ("…" if len(message) > 200 else "")
    embed = discord.Embed(
        title="\U0001f4e8 Relayed message",
        description=f"From {source.mention}\n\n> {preview}",
        color=COLOR_RELAY,
    )
    embed.add_field(name="Jump", value=f"[Go to {source.name}]({source.jump_url})", inline=False)
    return embed
