"""Discord's bindings for the shared message chunker.

The chunking and table-rendering logic moved to
:mod:`claude_code_core.rendering` so every frontend gets it. What stays here
is the part that is genuinely about Discord: its 2,000-character message
limit, and the width its code-block font can show without wrapping.

Existing imports keep working — this module re-exports the same names with the
same behaviour, so callers that only ever talk to Discord need no change.
"""

from __future__ import annotations

from claude_code_core.frontend import SurfaceCapabilities
from claude_code_core.rendering.chunker import FENCE_REOPEN_RESERVE, wrap_tables_in_fences
from claude_code_core.rendering.chunker import chunk_message as _chunk_message

DISCORD_MAX_CHARS = 2000
# Leave room for fence reopening overhead
EFFECTIVE_MAX = DISCORD_MAX_CHARS - FENCE_REOPEN_RESERVE

#: Width a Discord code block shows without wrapping on a typical client.
DISCORD_MONOSPACE_WIDTH = 55

DISCORD_CAPABILITIES = SurfaceCapabilities(
    max_message_chars=DISCORD_MAX_CHARS,
    supports_headings=True,
    supports_inline_images=True,
    supports_message_edit=True,
    supports_message_delete=True,
    supports_reactions=True,
    supports_slash_commands=True,
    supports_pinned_dashboard=True,
    supports_thread_rename=True,
    # Discord does not rate-limit edits by the hour the way Teams does; the
    # 1.5s streaming pace is the real constraint.
    live_update_budget_per_hour=1_000_000,
    stream_min_interval=1.5,
    max_files_per_message=10,
    max_file_bytes=8 * 1024 * 1024,
    file_delivery="inline",
    monospace_width=DISCORD_MONOSPACE_WIDTH,
    # Discord's code-block font does not render CJK at exactly 2x ASCII, so
    # box-drawn CJK tables would be visibly crooked. Fall back to vertical.
    monospace_cjk_is_double_width=False,
)


def chunk_message(text: str, max_chars: int = EFFECTIVE_MAX) -> list[str]:
    """Split a message into Discord-safe chunks."""
    return _chunk_message(
        text,
        max_chars,
        monospace_width=DISCORD_MONOSPACE_WIDTH,
        cjk_is_double_width=False,
    )


def _wrap_tables_in_fences(text: str) -> str:
    """Render GFM pipe-tables for Discord and wrap them in code fences."""
    return wrap_tables_in_fences(
        text,
        max_width=DISCORD_MONOSPACE_WIDTH,
        cjk_is_double_width=False,
    )


__all__ = [
    "DISCORD_CAPABILITIES",
    "DISCORD_MAX_CHARS",
    "DISCORD_MONOSPACE_WIDTH",
    "EFFECTIVE_MAX",
    "chunk_message",
]
