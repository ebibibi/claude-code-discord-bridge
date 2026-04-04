"""Box-drawing table renderer inspired by Claude Code's terminal table rendering.

Parses GFM pipe-tables and renders them with Unicode box-drawing characters
(┌─┬┐ ├─┼┤ └─┴┘ │) for clean display in Discord code blocks.

When the table is too wide for the available width, falls back to a vertical
key:value layout where each row becomes a labeled record.

Algorithm (adapted from Claude Code's ou4 component):
1. Parse GFM table lines → headers, alignments, rows
2. Compute per-column min (word) and max (line) widths using display_width
3. Three-tier width fitting: natural → proportional → hard-wrap
4. Render box-drawing table, or fall back to vertical layout

Key difference from v1: all width calculations use ``display_width()``
(East Asian Width aware) instead of ``len()``, and text wrapping uses
``wrap_cjk()`` instead of ``textwrap.wrap()``. This ensures correct
alignment for CJK (Japanese, Chinese, Korean) characters which occupy
2 columns in monospace fonts.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# --- Constants (mirroring Claude Code's ou4) ---
MIN_COL_WIDTH = 3  # Gt6: minimum characters per column
MAX_WRAP_LINES = 4  # HDz: max wrapped lines before switching to vertical
DEFAULT_MAX_WIDTH = 55  # Reasonable default for Discord code blocks


# --- East Asian Width support (mirrors Claude Code's J1/S25) ---


def display_width(text: str) -> int:
    """Return the display width of *text* in monospace terminal columns.

    Full-width characters (CJK ideographs, fullwidth forms) count as 2,
    everything else counts as 1. This mirrors Claude Code's ``J1()``
    function which uses ``Bun.stringWidth`` / the hand-rolled ``S25``.
    """
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ("W", "F") else 1
    return width


def wrap_cjk(text: str, width: int) -> list[str]:
    """Word-wrap *text* respecting display width of CJK characters.

    Unlike ``textwrap.wrap()``, this function:
    - Uses ``display_width()`` instead of ``len()`` for line width
    - Allows breaking between CJK characters (no space needed)
    - Falls back to character-level breaking when words exceed width
    """
    if not text:
        return [""]
    if width <= 0:
        return [text]

    lines: list[str] = []
    current = ""
    current_width = 0

    i = 0
    while i < len(text):
        ch = text[i]
        ch_width = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

        # Space-based word boundary for ASCII
        if ch == " ":
            # Try to keep the next word on the same line
            next_space = text.find(" ", i + 1)
            if next_space == -1:
                next_space = len(text)
            next_word = text[i + 1 : next_space]
            next_word_width = display_width(next_word)

            if current_width + 1 + next_word_width <= width:
                current += ch
                current_width += 1
                i += 1
                continue
            # Word doesn't fit → break here
            if current:
                lines.append(current)
                current = ""
                current_width = 0
            i += 1  # skip the space
            continue

        # Would this character overflow? Flush current line if non-empty.
        if current_width + ch_width > width and current:
            lines.append(current)
            current = ""
            current_width = 0

        current += ch
        current_width += ch_width
        i += 1

    if current:
        lines.append(current)

    return lines if lines else [""]


@dataclass(frozen=True)
class GfmTable:
    """Parsed GFM pipe-table."""

    headers: list[str]
    alignments: list[str]  # "left", "center", or "right"
    rows: list[list[str]]


def parse_gfm_table(lines: list[str]) -> GfmTable | None:
    """Parse GFM pipe-table lines into structured data.

    Returns None if lines don't form a valid GFM table.
    A valid table needs at least a header row and a separator row.
    """
    if len(lines) < 2:
        return None

    header_cells = _parse_row(lines[0])
    if not header_cells:
        return None

    sep_cells = _parse_row(lines[1])
    if not sep_cells:
        return None

    # Validate separator row: each cell must be dashes with optional colons
    alignments: list[str] = []
    for cell in sep_cells:
        stripped = cell.strip()
        if not stripped:
            return None
        inner = stripped.strip(":")
        if not inner or not all(c == "-" for c in inner):
            return None
        if stripped.startswith(":") and stripped.endswith(":"):
            alignments.append("center")
        elif stripped.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")

    num_cols = len(header_cells)

    while len(alignments) < num_cols:
        alignments.append("left")

    rows: list[list[str]] = []
    for line in lines[2:]:
        cells = _parse_row(line)
        if cells is not None:
            padded = cells[:num_cols]
            while len(padded) < num_cols:
                padded.append("")
            rows.append(padded)

    return GfmTable(headers=header_cells, alignments=alignments[:num_cols], rows=rows)


def render_table(
    table: GfmTable | None,
    max_width: int = DEFAULT_MAX_WIDTH,
) -> str | None:
    """Render a parsed GFM table, auto-selecting box or vertical layout.

    CJK-containing tables always use vertical layout because Discord's
    monospace code block font does not render CJK characters at exactly
    2x the width of ASCII characters, making column alignment impossible.
    """
    if table is None:
        return None

    # CJK content → always vertical (Discord font alignment issue)
    if _table_has_cjk(table):
        return render_vertical_table(table, max_width)

    num_cols = len(table.headers)
    border_overhead = 1 + num_cols * 3
    available = max(max_width - border_overhead, num_cols * MIN_COL_WIDTH)

    col_widths = _compute_col_widths(table, available)

    if _max_wrap_lines(table, col_widths) > MAX_WRAP_LINES:
        return render_vertical_table(table, max_width)

    result = render_box_table(table, max_width, col_widths)

    # Safety check: if any line exceeds max_width in display width, fall back
    if any(display_width(line) > max_width for line in result.splitlines()):
        return render_vertical_table(table, max_width)

    return result


def render_box_table(
    table: GfmTable,
    max_width: int = DEFAULT_MAX_WIDTH,
    col_widths: list[int] | None = None,
) -> str:
    """Render a table with Unicode box-drawing borders."""
    num_cols = len(table.headers)

    if col_widths is None:
        border_overhead = 1 + num_cols * 3
        available = max(max_width - border_overhead, num_cols * MIN_COL_WIDTH)
        col_widths = _compute_col_widths(table, available)

    lines: list[str] = []
    lines.append(_border_line("top", col_widths))
    lines.extend(_render_row(table.headers, col_widths, ["center"] * num_cols))
    lines.append(_border_line("middle", col_widths))

    for row in table.rows:
        lines.extend(_render_row(row, col_widths, table.alignments))

    lines.append(_border_line("bottom", col_widths))
    return "\n".join(lines)


def render_vertical_table(
    table: GfmTable,
    max_width: int = DEFAULT_MAX_WIDTH,
) -> str:
    """Render table in vertical key:value layout (one record per row)."""
    sep_width = min(max_width - 1, 40)
    separator = "-" * sep_width
    blocks: list[str] = []

    for row in table.rows:
        record_lines: list[str] = []
        for col_idx, header in enumerate(table.headers):
            value = row[col_idx] if col_idx < len(row) else ""
            label = f"{header}:"
            label_width = display_width(label)
            first_line_avail = max(max_width - label_width - 1, 10)
            wrapped = wrap_cjk(value, first_line_avail) if value else [""]
            record_lines.append(f"{label} {wrapped[0]}")
            for cont in wrapped[1:]:
                record_lines.append(f"  {cont}")
        blocks.append("\n".join(record_lines))

    return f"\n{separator}\n".join(blocks)


# --- Private helpers ---


def _parse_row(line: str) -> list[str] | None:
    """Parse a pipe-delimited row into a list of cell values."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    parts = stripped.split("|")
    if len(parts) < 3:
        return None
    return [p.strip() for p in parts[1:-1]]


def _compute_col_widths(table: GfmTable, available: int) -> list[int]:
    """Compute optimal column widths using Claude Code's 3-tier algorithm.

    All width measurements use ``display_width()`` for CJK correctness.
    """
    num_cols = len(table.headers)
    all_cells = [table.headers, *table.rows]

    min_widths = [MIN_COL_WIDTH] * num_cols
    max_widths = [MIN_COL_WIDTH] * num_cols

    for row in all_cells:
        for col in range(min(len(row), num_cols)):
            cell = row[col]
            # Min: widest single word (display width)
            words = cell.split() if cell else [""]
            word_max = max((display_width(w) for w in words), default=0)
            min_widths[col] = max(min_widths[col], word_max)
            # Max: full cell display width
            max_widths[col] = max(max_widths[col], display_width(cell))

    total_min = sum(min_widths)
    total_max = sum(max_widths)

    if total_max <= available:
        return max_widths

    if total_min <= available:
        extra = available - total_min
        stretches = [max_widths[i] - min_widths[i] for i in range(num_cols)]
        total_stretch = sum(stretches)
        if total_stretch == 0:
            return min_widths
        result = list(min_widths)
        for i in range(num_cols):
            result[i] += int(stretches[i] / total_stretch * extra)
        return result

    ratio = available / total_min if total_min > 0 else 1
    return [max(int(min_widths[i] * ratio), MIN_COL_WIDTH) for i in range(num_cols)]


def _table_has_cjk(table: GfmTable) -> bool:
    """Return True if any cell contains CJK (wide) characters.

    Discord's monospace font doesn't render CJK at exactly 2x ASCII width,
    so column-aligned box tables won't display correctly with CJK content.
    """
    all_cells = [table.headers, *table.rows]
    for row in all_cells:
        for cell in row:
            for ch in cell:
                if unicodedata.east_asian_width(ch) in ("W", "F"):
                    return True
    return False


def _max_wrap_lines(table: GfmTable, col_widths: list[int]) -> int:
    """Return the maximum number of wrapped lines any single cell produces."""
    max_lines = 1
    all_cells = [table.headers, *table.rows]
    for row in all_cells:
        for col in range(min(len(row), len(col_widths))):
            cell = row[col]
            if not cell:
                continue
            wrapped = wrap_cjk(cell, col_widths[col])
            max_lines = max(max_lines, len(wrapped))
    return max_lines


def _border_line(position: str, col_widths: list[int]) -> str:
    """Build a horizontal border line.

    Uses ASCII characters (+, -) instead of Unicode box-drawing to avoid
    misalignment in Discord mobile code blocks where ─ and │ may render
    at a different width than regular ASCII characters.
    """
    segments = ["-" * (w + 2) for w in col_widths]
    return "+" + "+".join(segments) + "+"


def _render_row(
    cells: list[str],
    col_widths: list[int],
    alignments: list[str],
) -> list[str]:
    """Render a single row, potentially spanning multiple output lines."""
    num_cols = len(col_widths)
    wrapped: list[list[str]] = []

    for col in range(num_cols):
        cell = cells[col] if col < len(cells) else ""
        lines = wrap_cjk(cell, col_widths[col]) if cell else [""]
        if not lines:
            lines = [""]
        wrapped.append(lines)

    max_lines = max(len(w) for w in wrapped)

    output_lines: list[str] = []
    for line_idx in range(max_lines):
        parts: list[str] = []
        for col in range(num_cols):
            cell_lines = wrapped[col]
            offset = (max_lines - len(cell_lines)) // 2
            actual_idx = line_idx - offset
            text = cell_lines[actual_idx] if 0 <= actual_idx < len(cell_lines) else ""
            align = alignments[col] if col < len(alignments) else "left"
            padded = _pad_cell(text, col_widths[col], align)
            parts.append(f" {padded} ")
        output_lines.append("|" + "|".join(parts) + "|")

    return output_lines


def _pad_cell(text: str, width: int, align: str) -> str:
    """Pad cell content to the specified width respecting display width."""
    text_width = display_width(text)
    padding = max(0, width - text_width)
    if align == "center":
        left_pad = padding // 2
        return " " * left_pad + text + " " * (padding - left_pad)
    if align == "right":
        return " " * padding + text
    return text + " " * padding
