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

AUTOCOMPACT_THRESHOLD = 83.5


CATEGORY_ICON: dict[ToolCategory, str] = {
    ToolCategory.READ: "\U0001f4d6",  # 📖
    ToolCategory.EDIT: "\u270f\ufe0f",  # ✏️
    ToolCategory.COMMAND: "\U0001f527",  # 🔧
    ToolCategory.WEB: "\U0001f310",  # 🌐
    ToolCategory.THINK: "\U0001f4ad",  # 💭
    ToolCategory.OTHER: "\U0001f916",  # 🤖
}


def tool_use_embed(
    tool: ToolUseEvent,
    in_progress: bool = True,
    elapsed_s: int | None = None,
) -> discord.Embed:
    """Create an embed for a tool use event.

    Args:
        tool: The tool use event to display.
        in_progress: Whether the tool is still running.
        elapsed_s: Seconds elapsed since the tool started. When provided and
                   the tool is in-progress, elapsed time is shown in the
                   description so the title (command name) stays stable.
    """
    icon = CATEGORY_ICON.get(tool.category, "\U0001f916")
    title = f"{icon} {tool.display_name}{'...' if in_progress else ''}"

    embed = discord.Embed(
        title=title[:256],
        color=COLOR_TOOL if in_progress else COLOR_INFO,
    )
    if in_progress and elapsed_s is not None:
        embed.description = f"⏳ {elapsed_s}s elapsed..."
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
    context_window: int | None = None,
    cache_creation_tokens: int | None = None,
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

    if context_window and input_tokens is not None:
        # Context window usage = prompt tokens only (input + cache reads/creation).
        # Output tokens are NOT included — they are not yet "in" the context window;
        # they will be added as cached input on the next turn.
        # This matches Claude Code's own lrH() calculation in the CLI source.
        context_used = input_tokens + (cache_read_tokens or 0) + (cache_creation_tokens or 0)
        usage_pct = min(100.0, context_used / context_window * 100)
        remaining_pct = max(0.0, AUTOCOMPACT_THRESHOLD - usage_pct)
        ctx_str = f"\U0001f4ca {usage_pct:.0f}% ctx"
        if usage_pct < AUTOCOMPACT_THRESHOLD:
            ctx_str += f" ({remaining_pct:.0f}% until compact)"
        else:
            ctx_str += " \u26a0\ufe0f"
        parts.append(ctx_str)

    description = " | ".join(parts) if parts else None

    embed = discord.Embed(
        title="\u2705 Done",
        description=description,
        color=COLOR_SUCCESS,
    )

    if context_window and input_tokens is not None:
        context_used = input_tokens + (cache_read_tokens or 0) + (cache_creation_tokens or 0)
        usage_pct = min(100.0, context_used / context_window * 100)
        if usage_pct >= AUTOCOMPACT_THRESHOLD:
            embed.set_footer(
                text=f"\u26a0\ufe0f Context {usage_pct:.0f}% full"
                " \u2014 auto-compact may run on next turn"
            )

    return embed


def tool_result_embed(tool_title: str, result_content: str) -> discord.Embed:
    """Create an embed for a completed tool with its result.

    Replaces the in-progress tool embed once the result is available.
    Uses description (4096-char limit) rather than a field (1024-char limit)
    so that up to ~30 lines of output can be shown without truncation.
    """
    # Strip the trailing "..." from in-progress title
    title = tool_title.rstrip(".")
    embed = discord.Embed(
        title=title[:256],
        color=COLOR_INFO,
    )
    if result_content:
        # Reserve 8 chars for code block markers (```\n … \n```)
        max_content = 4096 - 8
        display = result_content[:max_content]
        embed.description = f"```\n{display}\n```"
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
