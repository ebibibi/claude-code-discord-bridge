"""Fence-aware message chunker.

Inspired by OpenClaw: never split inside a code block. If forced to split,
properly close and reopen the fence markers.

GFM pipe-tables are rendered with Unicode box-drawing characters (Claude Code
style) and wrapped in triple-backtick fences before chunking. This gives
consistent monospace rendering for any table size: small tables that fit in
one message and large tables that must be split across messages both appear
with correct column alignment.

How much this module has to do varies enormously by surface, which is why
:func:`render_for` takes capabilities rather than a number. Discord caps a
message at 2,000 characters, so a long answer is chopped into a stream of
fragments. Teams allows roughly 100 KB, so the same answer usually arrives
whole — the splitting machinery below simply never fires. Reading the limit
from the surface is what lets the better experience happen on its own instead
of every frontend inheriting Discord's.
"""

from __future__ import annotations

from claude_code_core.frontend import SurfaceCapabilities
from claude_code_core.rendering.tables import parse_gfm_table, render_table

# Headroom for the ```lang fence a split may have to reopen with.
FENCE_REOPEN_RESERVE = 50


def render_for(text: str, caps: SurfaceCapabilities) -> list[str]:
    """Prepare assistant text for delivery on a surface.

    Converts GFM tables to whatever that surface can actually display, then
    splits the result to fit its message limit. Returns the messages to send,
    in order — often a single element.
    """
    prepared = wrap_tables_in_fences(
        text,
        max_width=caps.monospace_width,
        cjk_is_double_width=caps.monospace_cjk_is_double_width,
    )
    budget = max(caps.max_message_chars - FENCE_REOPEN_RESERVE, 1)
    return chunk_message(prepared, max_chars=budget, wrap_tables=False)


def chunk_message(
    text: str,
    max_chars: int,
    *,
    wrap_tables: bool = True,
    monospace_width: int | None = None,
    cjk_is_double_width: bool = False,
) -> list[str]:
    """Split a message into chunks that fit *max_chars*.

    Rules:
    1. Wrap GFM pipe-tables in code fences for consistent monospace rendering
    2. Prefer splitting at paragraph boundaries (blank lines)
    3. Never split inside a code fence if possible
    4. If forced to split inside a fence, close it and reopen in next chunk
    5. Respect max_chars limit per chunk

    Set ``wrap_tables=False`` when the caller has already rendered tables
    (as :func:`render_for` does) so the pass is not repeated.
    """
    if not text:
        return []

    if wrap_tables:
        text = wrap_tables_in_fences(
            text,
            max_width=monospace_width,
            cjk_is_double_width=cjk_is_double_width,
        )

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Find a good split point
        split_at = _find_split_point(remaining, max_chars)
        chunk = remaining[:split_at].rstrip()
        remaining = remaining[split_at:].lstrip("\n")

        # Handle fence state
        chunk, fence_lang = _close_open_fence(chunk)
        chunks.append(chunk)

        # Reopen fence in next chunk if needed
        if fence_lang is not None:
            remaining = f"```{fence_lang}\n{remaining}"

    return [c for c in chunks if c.strip()]


def wrap_tables_in_fences(
    text: str,
    *,
    max_width: int | None = None,
    cjk_is_double_width: bool = False,
) -> str:
    """Render GFM pipe-tables as box-drawing tables and wrap in code fences.

    Collects consecutive pipe-table lines, renders them with Unicode
    box-drawing characters via ``render_table``, and wraps the result in a
    triple-backtick code fence.  If the renderer cannot parse the lines
    (e.g. missing separator row), the raw pipe-table lines are fenced as-is.

    Tables already inside a code fence are left untouched.
    """
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_fence = False
    table_lines: list[str] = []

    for line in lines:
        stripped = line.rstrip("\n\r")

        # Track outer code fences — don't double-wrap already-fenced content
        if stripped.strip().startswith("```"):
            if table_lines:
                _flush_table(table_lines, result, max_width, cjk_is_double_width)
                table_lines = []
            in_fence = not in_fence
            result.append(line)
            continue

        if in_fence:
            result.append(line)
            continue

        is_table = _is_table_line(stripped)

        if is_table:
            table_lines.append(stripped)
        else:
            if table_lines:
                _flush_table(table_lines, result, max_width, cjk_is_double_width)
                table_lines = []
            result.append(line)

    if table_lines:
        _flush_table(table_lines, result, max_width, cjk_is_double_width)

    return "".join(result)


def _flush_table(
    table_lines: list[str],
    result: list[str],
    max_width: int | None = None,
    cjk_is_double_width: bool = False,
) -> None:
    """Render collected table lines and append fenced output to *result*."""
    parsed = parse_gfm_table(table_lines)
    rendered = None
    if parsed:
        if max_width is None:
            rendered = render_table(parsed, cjk_is_double_width=cjk_is_double_width)
        else:
            rendered = render_table(parsed, max_width, cjk_is_double_width=cjk_is_double_width)

    _ensure_newline(result)
    result.append("```\n")
    if rendered:
        result.append(rendered)
        result.append("\n")
    else:
        # Fallback: raw pipe-table lines
        for tl in table_lines:
            result.append(tl)
            result.append("\n")
    result.append("```\n")


def _ensure_newline(parts: list[str]) -> None:
    """Append a newline to *parts* if the last part does not end with one.

    Used by ``_wrap_tables_in_fences`` to guarantee that a closing fence
    marker always starts on its own line, even when the last table row
    was not terminated with a newline.
    """
    if parts and not parts[-1].endswith("\n"):
        parts.append("\n")


def _find_split_point(text: str, max_chars: int) -> int:
    """Find the best position to split the text.

    Preference order:
    1. Paragraph break (blank line) before max_chars
    2. Line break before max_chars
    3. Hard split at max_chars
    """
    search_region = text[:max_chars]

    # Search backward from max_chars for a blank line
    last_paragraph = search_region.rfind("\n\n")
    if last_paragraph > max_chars // 3:
        return last_paragraph + 1

    # Search backward for any newline
    last_newline = search_region.rfind("\n")
    return last_newline + 1 if last_newline > max_chars // 3 else max_chars


def _is_table_line(line: str) -> bool:
    """Return True if *line* looks like a markdown table row.

    A table row must start **and** end with a pipe character (after stripping
    whitespace) and contain at least one character between the pipes.
    """
    stripped = line.strip()
    return len(stripped) >= 3 and stripped.startswith("|") and stripped.endswith("|")


def _close_open_fence(chunk: str) -> tuple[str, str | None]:
    """If the chunk has an unclosed code fence, close it.

    Returns:
        Tuple of (possibly modified chunk, fence language or None).
        fence language is None if no fence was open, "" if no language specified.
    """
    fence_count = 0
    fence_lang = ""
    lines = chunk.split("\n")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if fence_count % 2 == 0:
                # Opening fence
                fence_lang = stripped[3:].strip()
                fence_count += 1
            else:
                # Closing fence
                fence_count += 1

    # If odd number of fences, the last one is unclosed
    if fence_count % 2 == 1:
        return chunk + "\n```", fence_lang

    return chunk, None
