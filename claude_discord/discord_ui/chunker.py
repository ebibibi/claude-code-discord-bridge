"""Fence-aware message chunker for Discord's 2000-character limit.

Inspired by OpenClaw: never split inside a code block. If forced to split,
properly close and reopen the fence markers.

GFM pipe-tables are wrapped in triple-backtick fences before chunking.
This gives consistent monospace rendering in Discord for any table size:
small tables that fit in one message and large tables that must be split
across messages both appear with correct column alignment.
"""

from __future__ import annotations

DISCORD_MAX_CHARS = 2000
# Leave room for fence reopening overhead
EFFECTIVE_MAX = DISCORD_MAX_CHARS - 50


def chunk_message(text: str, max_chars: int = EFFECTIVE_MAX) -> list[str]:
    """Split a message into Discord-safe chunks.

    Rules:
    1. Wrap GFM pipe-tables in code fences for consistent monospace rendering
    2. Prefer splitting at paragraph boundaries (blank lines)
    3. Never split inside a code fence if possible
    4. If forced to split inside a fence, close it and reopen in next chunk
    5. Respect max_chars limit per chunk
    """
    if not text:
        return []

    text = _wrap_tables_in_fences(text)

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


def _wrap_tables_in_fences(text: str) -> str:
    """Wrap every GFM pipe-table block in a triple-backtick code fence.

    Discord renders GFM tables natively only when the complete table fits in
    a single message.  When a large table must be split, continuation chunks
    have no header and appear as raw pipe characters.  Wrapping tables in
    code fences lets the existing fence-aware chunker handle splitting with
    proper close/reopen semantics, giving monospace alignment in every chunk.

    Tables already inside a code fence are left untouched.
    """
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_fence = False
    in_table = False

    for line in lines:
        stripped = line.rstrip("\n\r")

        # Track outer code fences — don't double-wrap already-fenced content
        if stripped.strip().startswith("```"):
            if in_table:
                # Close the table fence before the outer fence opens
                _ensure_newline(result)
                result.append("```\n")
                in_table = False
            in_fence = not in_fence
            result.append(line)
            continue

        if in_fence:
            result.append(line)
            continue

        is_table = _is_table_line(stripped)

        if is_table and not in_table:
            result.append("```\n")
            in_table = True
        elif not is_table and in_table:
            _ensure_newline(result)
            result.append("```\n")
            in_table = False

        result.append(line)

    if in_table:
        _ensure_newline(result)
        result.append("```\n")

    return "".join(result)


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
