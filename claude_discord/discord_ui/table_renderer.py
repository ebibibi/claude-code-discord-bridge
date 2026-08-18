"""Re-export of the shared table renderer.

The implementation moved to :mod:`claude_code_core.rendering.tables` — every
frontend needs it, because neither Discord nor Teams renders GFM pipe-tables
natively. This module remains so existing imports keep working.
"""

from __future__ import annotations

from claude_code_core.rendering.tables import (
    DEFAULT_MAX_WIDTH,
    MAX_WRAP_LINES,
    MIN_COL_WIDTH,
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
    "MAX_WRAP_LINES",
    "MIN_COL_WIDTH",
    "GfmTable",
    "display_width",
    "parse_gfm_table",
    "render_box_table",
    "render_table",
    "render_vertical_table",
    "wrap_cjk",
]
