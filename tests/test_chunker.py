"""Tests for fence-aware message chunker."""

from claude_discord.discord_ui.chunker import (
    _close_open_fence,
    _is_table_line,
    chunk_message,
)


class TestChunkMessage:
    def test_short_message_no_split(self):
        text = "Hello world"
        chunks = chunk_message(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_message(self):
        chunks = chunk_message("")
        assert chunks == []

    def test_splits_at_paragraph(self):
        text = "A" * 500 + "\n\n" + "B" * 500
        chunks = chunk_message(text, max_chars=600)
        assert len(chunks) == 2
        assert chunks[0].strip().startswith("A")
        assert chunks[1].strip().startswith("B")

    def test_splits_at_newline(self):
        text = "A" * 500 + "\n" + "B" * 500
        chunks = chunk_message(text, max_chars=600)
        assert len(chunks) == 2

    def test_hard_split(self):
        text = "A" * 2000
        chunks = chunk_message(text, max_chars=800)
        assert len(chunks) >= 2
        total = sum(len(c) for c in chunks)
        assert total == 2000

    def test_preserves_code_fence(self):
        text = "Before\n```python\n" + "x = 1\n" * 200 + "```\nAfter"
        chunks = chunk_message(text, max_chars=500)
        assert len(chunks) >= 2
        for i, chunk in enumerate(chunks):
            fence_count = chunk.count("```")
            assert fence_count % 2 == 0, f"Chunk {i} has unbalanced fences: {fence_count}"

    def test_no_empty_chunks(self):
        text = "Hello\n\n\n\nWorld"
        chunks = chunk_message(text, max_chars=10)
        assert all(c.strip() for c in chunks)


TABLE_3ROW = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"


class TestIsTableLine:
    def test_table_row(self):
        assert _is_table_line("| Col1 | Col2 |")

    def test_separator_row(self):
        assert _is_table_line("|------|------|")

    def test_not_table(self):
        assert not _is_table_line("Just a normal line")

    def test_empty_line(self):
        assert not _is_table_line("")

    def test_partial_pipe_only_start(self):
        assert not _is_table_line("| only starts with pipe")


class TestTableChunking:
    def test_table_not_split(self):
        """A table that fits within a single chunk must not be split."""
        text = "Intro paragraph.\n\n" + TABLE_3ROW
        chunks = chunk_message(text)
        assert any(TABLE_3ROW in chunk for chunk in chunks)

    def test_splits_before_table(self):
        """Long preamble followed by a table: split before the table, not inside it."""
        # 880 + "\n\n" (2) + table (~38) = ~920 > max_chars=900
        preamble = "X" * 880
        text = preamble + "\n\n" + TABLE_3ROW
        chunks = chunk_message(text, max_chars=900)
        assert len(chunks) >= 2
        assert any(TABLE_3ROW in chunk for chunk in chunks)

    def test_table_at_message_start(self):
        """Table at the very start is returned intact if it fits."""
        text = TABLE_3ROW + "\n\nTrailing text."
        chunks = chunk_message(text)
        assert any(TABLE_3ROW in chunk for chunk in chunks)

    def test_header_and_separator_in_same_chunk(self):
        """Header and separator rows must never end up in different chunks."""
        header = "| Col |\n|-----|\n"
        many_rows = "| val |\n" * 300  # ~2400 chars — forces multiple splits
        text = header + many_rows
        chunks = chunk_message(text, max_chars=500)
        for chunk in chunks:
            lines = [ln for ln in chunk.splitlines() if _is_table_line(ln)]
            if not lines:
                continue
            # A separator-only row as the first table line means the header
            # ended up in a previous chunk — Discord cannot render that.
            first_cell = lines[0].replace("|", "").replace("-", "").replace(" ", "")
            assert first_cell != "", f"Chunk starts with separator row (no header): {chunk[:120]!r}"


class TestCloseOpenFence:
    def test_no_fence(self):
        chunk, lang = _close_open_fence("Hello world")
        assert chunk == "Hello world"
        assert lang is None

    def test_balanced_fence(self):
        chunk, lang = _close_open_fence("```python\ncode\n```")
        assert lang is None

    def test_unclosed_fence(self):
        chunk, lang = _close_open_fence("```python\ncode")
        assert chunk.endswith("```")
        assert lang == "python"

    def test_unclosed_fence_no_lang(self):
        chunk, lang = _close_open_fence("```\ncode")
        assert chunk.endswith("```")
        assert lang == ""

    def test_multiple_fences_last_unclosed(self):
        text = "```\nfirst\n```\ntext\n```js\nsecond"
        chunk, lang = _close_open_fence(text)
        assert chunk.endswith("```")
        assert lang == "js"

    def test_multiple_fences_all_closed(self):
        text = "```\nfirst\n```\n```\nsecond\n```"
        chunk, lang = _close_open_fence(text)
        assert lang is None
