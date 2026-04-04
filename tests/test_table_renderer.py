"""Tests for box-drawing table renderer (Claude Code style)."""

from claude_discord.discord_ui.table_renderer import (
    parse_gfm_table,
    render_box_table,
    render_table,
    render_vertical_table,
)


class TestParseGfmTable:
    def test_simple_table(self):
        lines = [
            "| Name | Age |",
            "|------|-----|",
            "| Alice | 30 |",
            "| Bob | 25 |",
        ]
        table = parse_gfm_table(lines)
        assert table is not None
        assert table.headers == ["Name", "Age"]
        assert table.rows == [["Alice", "30"], ["Bob", "25"]]

    def test_alignment_detection(self):
        lines = [
            "| Left | Center | Right |",
            "|:-----|:------:|------:|",
            "| a | b | c |",
        ]
        table = parse_gfm_table(lines)
        assert table is not None
        assert table.alignments == ["left", "center", "right"]

    def test_default_alignment_is_left(self):
        lines = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
        ]
        table = parse_gfm_table(lines)
        assert table is not None
        assert table.alignments == ["left", "left"]

    def test_invalid_table_no_separator(self):
        lines = [
            "| A | B |",
            "| 1 | 2 |",
        ]
        table = parse_gfm_table(lines)
        assert table is None

    def test_single_column(self):
        lines = [
            "| Name |",
            "|------|",
            "| Alice |",
        ]
        table = parse_gfm_table(lines)
        assert table is not None
        assert table.headers == ["Name"]
        assert table.rows == [["Alice"]]

    def test_empty_cells(self):
        lines = [
            "| A | B |",
            "|---|---|",
            "| 1 |  |",
            "|  | 2 |",
        ]
        table = parse_gfm_table(lines)
        assert table is not None
        assert table.rows == [["1", ""], ["", "2"]]

    def test_too_few_lines(self):
        lines = ["| A |"]
        assert parse_gfm_table(lines) is None

    def test_mismatched_columns_padded(self):
        """Rows with fewer columns than header get empty-string padding."""
        lines = [
            "| A | B | C |",
            "|---|---|---|",
            "| 1 |",
        ]
        table = parse_gfm_table(lines)
        assert table is not None
        assert table.rows == [["1", "", ""]]


class TestRenderBoxTable:
    def test_simple_box(self):
        lines = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        assert "┌" in result
        assert "┐" in result
        assert "└" in result
        assert "┘" in result
        assert "│" in result
        assert "├" in result
        assert "┤" in result
        assert " A " in result
        assert " 1 " in result

    def test_respects_max_width(self):
        lines = [
            "| Name | Age |",
            "|------|-----|",
            "| Alice | 30 |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=30)
        for line in result.splitlines():
            assert len(line) <= 30, f"Line too wide: {line!r} ({len(line)} chars)"

    def test_alignment_left(self):
        lines = [
            "| A |",
            "|:--|",
            "| hello |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        # Left-aligned: content should be left-padded
        for line in result.splitlines():
            if "hello" in line:
                idx = line.index("hello")
                assert line[idx - 1] == " "  # one space padding

    def test_alignment_right(self):
        lines = [
            "| Num |",
            "|----:|",
            "| 42 |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        # Right-aligned: content should be right-padded
        for line in result.splitlines():
            if "42" in line:
                after_42 = line[line.index("42") + 2 :]
                # Should have spaces then │
                assert after_42.strip() == "│"

    def test_header_separator_between_header_and_body(self):
        lines = [
            "| H1 | H2 |",
            "|---|---|",
            "| a | b |",
            "| c | d |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        result_lines = result.splitlines()
        # Structure: top border, header, separator, row1, row2, bottom border
        assert result_lines[0].startswith("┌")
        assert "┬" in result_lines[0]
        assert result_lines[2].startswith("├")
        assert "┼" in result_lines[2]
        assert result_lines[-1].startswith("└")
        assert "┴" in result_lines[-1]

    def test_wide_content_wraps(self):
        lines = [
            "| Description |",
            "|---|",
            "| This is a very long description that should wrap |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=25)
        for line in result.splitlines():
            assert len(line) <= 25

    def test_no_rows(self):
        """Header-only table should still render."""
        lines = [
            "| A | B |",
            "|---|---|",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        assert "┌" in result
        assert " A " in result
        assert "└" in result


class TestRenderVerticalTable:
    def test_simple_vertical(self):
        lines = [
            "| Name | Age |",
            "|------|-----|",
            "| Alice | 30 |",
            "| Bob | 25 |",
        ]
        table = parse_gfm_table(lines)
        result = render_vertical_table(table, max_width=40)
        assert "Name:" in result
        assert "Alice" in result
        assert "Age:" in result
        assert "30" in result
        # Rows separated by ─
        assert "─" in result

    def test_separator_between_rows(self):
        lines = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "| 3 | 4 |",
        ]
        table = parse_gfm_table(lines)
        result = render_vertical_table(table, max_width=40)
        # Should have a separator line between records
        found_sep = False
        for line in result.splitlines():
            if line.strip() and all(c == "─" for c in line.strip()):
                found_sep = True
        assert found_sep

    def test_respects_max_width(self):
        lines = [
            "| Name | Value |",
            "|------|-------|",
            "| key | " + "x" * 100 + " |",
        ]
        table = parse_gfm_table(lines)
        result = render_vertical_table(table, max_width=40)
        for line in result.splitlines():
            assert len(line) <= 40


class TestRenderTable:
    """Test the main entry point that auto-selects box vs vertical."""

    def test_narrow_table_uses_box(self):
        lines = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
        ]
        table = parse_gfm_table(lines)
        result = render_table(table, max_width=40)
        assert "┌" in result  # box-drawing means box layout was chosen

    def test_very_wide_table_uses_vertical(self):
        """Table with many wide columns falls back to vertical."""
        cols = " | ".join([f"Column{i}" for i in range(10)])
        sep = " | ".join(["---"] * 10)
        vals = " | ".join([f"value{i}" for i in range(10)])
        lines = [
            f"| {cols} |",
            f"|{sep}|",
            f"| {vals} |",
        ]
        table = parse_gfm_table(lines)
        result = render_table(table, max_width=55)
        # Should fall back to vertical — no box-drawing top-left corner
        assert "┌" not in result
        assert ":" in result  # vertical format uses "Header: value"

    def test_returns_none_for_invalid_table(self):
        """Non-table input returns None."""
        result = render_table(None, max_width=40)
        assert result is None
