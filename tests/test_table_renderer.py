"""Tests for box-drawing table renderer (Claude Code style)."""

from claude_discord.discord_ui.table_renderer import (
    display_width,
    parse_gfm_table,
    render_box_table,
    render_table,
    render_vertical_table,
    wrap_cjk,
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
        # ASCII borders for Discord mobile compatibility
        assert "+" in result
        assert "-" in result
        assert "|" in result
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
            w = display_width(line)
            assert w <= 30, f"Line too wide: {line!r} ({w} cols)"

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
                # Should have spaces then |
                assert after_42.strip() == "|"

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
        assert result_lines[0].startswith("+")
        assert "+" in result_lines[0]
        assert result_lines[2].startswith("+")
        assert result_lines[-1].startswith("+")

    def test_wide_content_wraps(self):
        lines = [
            "| Description |",
            "|---|",
            "| This is a very long description that should wrap |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=25)
        for line in result.splitlines():
            w = display_width(line)
            assert w <= 25, f"Line too wide ({w}): {line!r}"

    def test_no_rows(self):
        """Header-only table should still render."""
        lines = [
            "| A | B |",
            "|---|---|",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        assert "+" in result
        assert " A " in result


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
        # Rows separated by -
        assert "-" in result

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
            if line.strip() and all(c == "-" for c in line.strip()):
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
            w = display_width(line)
            assert w <= 40, f"Line too wide ({w}): {line!r}"


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
        assert "+" in result  # border characters mean box layout was chosen

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
        # Should fall back to vertical — no border characters
        assert result.count("+") == 0
        assert ":" in result  # vertical format uses "Header: value"

    def test_returns_none_for_invalid_table(self):
        """Non-table input returns None."""
        result = render_table(None, max_width=40)
        assert result is None


class TestDisplayWidth:
    """display_width() — East Asian Width aware string width."""

    def test_ascii(self):
        assert display_width("hello") == 5

    def test_cjk_fullwidth(self):
        # 日本語の全角文字は2カラム
        assert display_width("東京") == 4

    def test_mixed(self):
        # "A東京B" = 1 + 2 + 2 + 1 = 6
        assert display_width("A東京B") == 6

    def test_empty(self):
        assert display_width("") == 0

    def test_emoji(self):
        # Basic emoji should be at least 1 wide
        w = display_width("🎉")
        assert w >= 1

    def test_halfwidth_katakana(self):
        # 半角カタカナ (U+FF61-FF9F) should be 1 column
        assert display_width("ｱｲｳ") == 3

    def test_fullwidth_katakana(self):
        # 全角カタカナ should be 2 columns each
        assert display_width("アイウ") == 6


class TestWrapCjk:
    """wrap_cjk() — CJK-aware text wrapping."""

    def test_ascii_no_wrap(self):
        result = wrap_cjk("hello", 10)
        assert result == ["hello"]

    def test_ascii_wraps(self):
        result = wrap_cjk("hello world", 6)
        assert len(result) >= 2

    def test_cjk_wraps_at_display_width(self):
        # "東京大阪名古屋" = 14 display columns. width=8 → should wrap
        result = wrap_cjk("東京大阪名古屋", 8)
        assert len(result) >= 2
        for line in result:
            assert display_width(line) <= 8

    def test_mixed_content(self):
        text = "Hello東京World"
        result = wrap_cjk(text, 8)
        for line in result:
            assert display_width(line) <= 8

    def test_empty_string(self):
        result = wrap_cjk("", 10)
        assert result == [""]

    def test_single_wide_char(self):
        result = wrap_cjk("東", 4)
        assert result == ["東"]


class TestCjkTableRendering:
    """CJK tables use vertical layout due to Discord font limitations."""

    def test_cjk_table_always_uses_vertical(self):
        """CJK-containing tables always render in vertical layout."""
        lines = [
            "| 言語 | 用途 |",
            "|------|------|",
            "| Python | AI |",
            "| Rust | システム |",
        ]
        table = parse_gfm_table(lines)
        result = render_table(table, max_width=40)
        # Should use vertical layout (no box borders)
        assert "+" not in result
        assert ":" in result
        assert "言語:" in result
        assert "Python" in result

    def test_cjk_box_still_works_directly(self):
        """render_box_table still works with CJK (for non-Discord use)."""
        lines = [
            "| 名前 | 年齢 |",
            "|------|------|",
            "| アリス | 30 |",
        ]
        table = parse_gfm_table(lines)
        result = render_box_table(table, max_width=40)
        widths = [display_width(line) for line in result.splitlines()]
        assert len(set(widths)) == 1, f"Misaligned widths: {widths}"

    def test_japanese_vertical_respects_max_width(self):
        lines = [
            "| 名前 | 年齢 |",
            "|------|------|",
            "| アリス | 30 |",
        ]
        table = parse_gfm_table(lines)
        result = render_vertical_table(table, max_width=30)
        for line in result.splitlines():
            w = display_width(line)
            assert w <= 30, f"Line too wide ({w}): {line!r}"

    def test_ascii_only_table_uses_box(self):
        """Tables without CJK should still use box layout."""
        lines = [
            "| Name | Age |",
            "|------|-----|",
            "| Alice | 30 |",
        ]
        table = parse_gfm_table(lines)
        result = render_table(table, max_width=40)
        assert "+" in result  # box layout
        assert ":" not in result  # not vertical
