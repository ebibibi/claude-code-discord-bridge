"""Box-drawing table renderer inspired by Claude Code's terminal table rendering.

Parses GFM pipe-tables and renders them with Unicode box-drawing characters
(┌─┬┐ ├─┼┤ └─┴┘ │) for clean display in Discord code blocks.

When the table is too wide for the available width, falls back to a vertical
key:value layout where each row becomes a labeled record.

Algorithm (adapted from Claude Code's ou4 component):
1. Parse GFM table lines → headers, alignments, rows
2. Compute per-column min (word) and max (line) widths
3. Three-tier width fitting: natural → proportional → hard-wrap
4. Render box-drawing table, or fall back to vertical layout
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

# --- Constants (mirroring Claude Code's ou4) ---
MIN_COL_WIDTH = 3  # Gt6: minimum characters per column
MAX_WRAP_LINES = 4  # HDz: max wrapped lines before switching to vertical
DEFAULT_MAX_WIDTH = 55  # Reasonable default for Discord code blocks


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
        # Remove colons and check for dashes
        inner = stripped.strip(":")
        if not inner or not all(c == "-" for c in inner):
            return None
        # Detect alignment
        if stripped.startswith(":") and stripped.endswith(":"):
            alignments.append("center")
        elif stripped.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")

    num_cols = len(header_cells)

    # Pad alignments if fewer than headers
    while len(alignments) < num_cols:
        alignments.append("left")

    rows: list[list[str]] = []
    for line in lines[2:]:
        cells = _parse_row(line)
        if cells is not None:
            # Pad or truncate to match header column count
            padded = cells[:num_cols]
            while len(padded) < num_cols:
                padded.append("")
            rows.append(padded)

    return GfmTable(headers=header_cells, alignments=alignments[:num_cols], rows=rows)


def render_table(table: GfmTable | None, max_width: int = DEFAULT_MAX_WIDTH) -> str | None:
    """Render a parsed GFM table, auto-selecting box or vertical layout.

    Returns None if table is None (invalid input).
    """
    if table is None:
        return None

    num_cols = len(table.headers)
    # Border overhead: │ + ( " content " + │) per column = 1 + 3*num_cols
    border_overhead = 1 + num_cols * 3
    available = max(max_width - border_overhead, num_cols * MIN_COL_WIDTH)

    col_widths = _compute_col_widths(table, available)

    # Check if any cell wraps more than MAX_WRAP_LINES
    if _max_wrap_lines(table, col_widths) > MAX_WRAP_LINES:
        return render_vertical_table(table, max_width)

    result = render_box_table(table, max_width, col_widths)

    # Safety check: if any line exceeds max_width, fall back
    if any(len(line) > max_width for line in result.splitlines()):
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


def render_vertical_table(table: GfmTable, max_width: int = DEFAULT_MAX_WIDTH) -> str:
    """Render table in vertical key:value layout (one record per row)."""
    sep_width = min(max_width - 1, 40)
    separator = "─" * sep_width
    blocks: list[str] = []

    for row in table.rows:
        record_lines: list[str] = []
        for col_idx, header in enumerate(table.headers):
            value = row[col_idx] if col_idx < len(row) else ""
            label = f"{header}:"
            # Available width for value on the first line
            first_line_avail = max(max_width - len(label) - 1, 10)
            wrapped = textwrap.wrap(value, width=first_line_avail) if value else [""]
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
    # Split by | and strip the empty first/last elements
    parts = stripped.split("|")
    # parts[0] and parts[-1] are empty strings from leading/trailing |
    if len(parts) < 3:
        return None
    return [p.strip() for p in parts[1:-1]]


def _compute_col_widths(table: GfmTable, available: int) -> list[int]:
    """Compute optimal column widths using Claude Code's 3-tier algorithm.

    Tier 1: All columns fit at natural max width
    Tier 2: Proportional distribution between min and max
    Tier 3: Scale everything down with hard-wrap
    """
    num_cols = len(table.headers)
    all_cells = [table.headers, *table.rows]

    # min width = max word length per column
    min_widths = [MIN_COL_WIDTH] * num_cols
    # max width = max line length per column
    max_widths = [MIN_COL_WIDTH] * num_cols

    for row in all_cells:
        for col in range(min(len(row), num_cols)):
            cell = row[col]
            # Min: longest single word
            words = cell.split() if cell else [""]
            word_max = max((len(w) for w in words), default=0)
            min_widths[col] = max(min_widths[col], word_max)
            # Max: full cell length
            max_widths[col] = max(max_widths[col], len(cell))

    total_min = sum(min_widths)
    total_max = sum(max_widths)

    # Tier 1: everything fits at max
    if total_max <= available:
        return max_widths

    # Tier 2: proportional distribution
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

    # Tier 3: scale down, hard-wrap
    ratio = available / total_min if total_min > 0 else 1
    return [max(int(min_widths[i] * ratio), MIN_COL_WIDTH) for i in range(num_cols)]


def _max_wrap_lines(table: GfmTable, col_widths: list[int]) -> int:
    """Return the maximum number of wrapped lines any single cell produces."""
    max_lines = 1
    all_cells = [table.headers, *table.rows]
    for row in all_cells:
        for col in range(min(len(row), len(col_widths))):
            cell = row[col]
            if not cell:
                continue
            wrapped = textwrap.wrap(cell, width=col_widths[col]) or [""]
            max_lines = max(max_lines, len(wrapped))
    return max_lines


def _border_line(position: str, col_widths: list[int]) -> str:
    """Build a horizontal border line with box-drawing characters."""
    chars = {
        "top": ("┌", "┬", "┐"),
        "middle": ("├", "┼", "┤"),
        "bottom": ("└", "┴", "┘"),
    }
    left, cross, right = chars[position]
    segments = ["─" * (w + 2) for w in col_widths]
    return left + cross.join(segments) + right


def _render_row(cells: list[str], col_widths: list[int], alignments: list[str]) -> list[str]:
    """Render a single row, potentially spanning multiple output lines."""
    num_cols = len(col_widths)
    wrapped: list[list[str]] = []

    for col in range(num_cols):
        cell = cells[col] if col < len(cells) else ""
        lines = textwrap.wrap(cell, width=col_widths[col]) if cell else [""]
        if not lines:
            lines = [""]
        wrapped.append(lines)

    max_lines = max(len(w) for w in wrapped)

    # Vertically center shorter cells
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
        output_lines.append("│" + "│".join(parts) + "│")

    return output_lines


def _pad_cell(text: str, width: int, align: str) -> str:
    """Pad cell content to the specified width with given alignment."""
    padding = max(0, width - len(text))
    if align == "center":
        left_pad = padding // 2
        return " " * left_pad + text + " " * (padding - left_pad)
    if align == "right":
        return " " * padding + text
    return text + " " * padding
