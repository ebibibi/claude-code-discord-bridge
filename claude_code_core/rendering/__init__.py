"""Frontend-agnostic rendering: turning assistant text into sendable messages.

Every chat surface has to answer the same two questions — how do I show a
table, and how do I split something too long — and the answers differ only by
numbers the surface itself knows. So the logic lives here and the numbers
arrive as :class:`~claude_code_core.frontend.SurfaceCapabilities`.
"""

from __future__ import annotations

from .chunker import FENCE_REOPEN_RESERVE, chunk_message, render_for, wrap_tables_in_fences
from .tables import (
    DEFAULT_MAX_WIDTH,
    GfmTable,
    display_width,
    parse_gfm_table,
    render_box_table,
    render_table,
    render_vertical_table,
    wrap_cjk,
)

__all__ = [
    "DEFAULT_MAX_WIDTH",
    "FENCE_REOPEN_RESERVE",
    "GfmTable",
    "chunk_message",
    "display_width",
    "parse_gfm_table",
    "render_box_table",
    "render_for",
    "render_table",
    "render_vertical_table",
    "wrap_cjk",
    "wrap_tables_in_fences",
]
