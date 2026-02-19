"""Tests for fence-aware message chunker."""

from claude_discord.discord_ui.chunker import (
    _close_open_fence,
    _is_table_line,
    _wrap_tables_in_fences,
    chunk_message,
)

TABLE_3ROW = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
FENCED_TABLE_3ROW = f"```\n{TABLE_3ROW}\n```"


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


class TestWrapTablesInFences:
    def test_simple_table_wrapped(self):
        """A bare table is wrapped in a code fence."""
        table = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = _wrap_tables_in_fences(table)
        assert result == f"```\n{table}\n```\n"

    def test_table_with_surrounding_text(self):
        """Table embedded in text gets fenced; surrounding text is untouched."""
        text = "Before.\n\n| A |\n|---|\n| 1 |\n\nAfter."
        result = _wrap_tables_in_fences(text)
        assert result.startswith("Before.")
        assert "```\n| A |" in result
        assert "| 1 |\n```" in result
        assert result.endswith("After.")

    def test_table_inside_fence_not_rewrapped(self):
        """Table rows already inside a code fence are left untouched."""
        fenced = "```\n| A | B |\n|---|---|\n| 1 | 2 |\n```"
        result = _wrap_tables_in_fences(fenced)
        assert result == fenced

    def test_no_table_unchanged(self):
        """Text without tables passes through unchanged."""
        text = "Just some regular text.\n\nAnd another paragraph."
        result = _wrap_tables_in_fences(text)
        assert result == text

    def test_multiple_tables_each_wrapped(self):
        """Each table block gets its own pair of fence markers."""
        text = "| A |\n|---|\n| 1 |\n\nMiddle.\n\n| B |\n|---|\n| 2 |"
        result = _wrap_tables_in_fences(text)
        assert result.count("```") == 4  # two open + two close fences

    def test_empty_text(self):
        assert _wrap_tables_in_fences("") == ""

    def test_code_fence_with_table_syntax_inside_untouched(self):
        """Pipe-like lines inside an existing code fence are not wrapped."""
        fenced = "```python\n# | not | a | table |\ncode()\n```"
        result = _wrap_tables_in_fences(fenced)
        assert result == fenced


class TestTableChunking:
    def test_table_wrapped_in_fence(self):
        """Tables should be wrapped in a code fence in the output."""
        text = "Intro paragraph.\n\n" + TABLE_3ROW
        chunks = chunk_message(text)
        full = "".join(chunks)
        assert FENCED_TABLE_3ROW in full

    def test_splits_before_table_fence(self):
        """Long preamble followed by a table: the fenced table stays in one chunk."""
        preamble = "X" * 880
        text = preamble + "\n\n" + TABLE_3ROW
        chunks = chunk_message(text, max_chars=900)
        assert len(chunks) >= 2
        # The fenced table should appear intact in one of the chunks
        assert any(FENCED_TABLE_3ROW in chunk for chunk in chunks)

    def test_table_at_message_start(self):
        """Table at the very start is returned intact (fenced) if it fits."""
        text = TABLE_3ROW + "\n\nTrailing text."
        chunks = chunk_message(text)
        full = "".join(chunks)
        assert FENCED_TABLE_3ROW in full

    def test_large_table_all_chunks_properly_fenced(self):
        """Large table split across chunks: every chunk with table content is fenced."""
        header = "| Col |\n|-----|\n"
        many_rows = "| val |\n" * 300  # ~2400 chars — forces multiple splits
        text = header + many_rows
        chunks = chunk_message(text, max_chars=500)
        for i, chunk in enumerate(chunks):
            if "| val |" in chunk or "| Col |" in chunk:
                fence_count = chunk.count("```")
                assert fence_count % 2 == 0, (
                    f"Chunk {i} has unbalanced fences: {chunk[:120]!r}"
                )


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
