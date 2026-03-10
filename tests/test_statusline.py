"""Tests for the statusline Discord runner (claude_discord.discord_ui.statusline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_discord.discord_ui.statusline import (
    _bars_to_unicode,
    build_statusline_json,
    convert_for_discord,
    read_statusline_command,
    render_statusline,
    strip_ansi,
)

# ---------------------------------------------------------------------------
# Pure-logic tests (no I/O)
# ---------------------------------------------------------------------------


class TestStripAnsi:
    def test_removes_color_codes(self) -> None:
        text = "\x1b[38;2;46;149;153mHello\x1b[0m"
        assert strip_ansi(text) == "Hello"

    def test_removes_bold_dim(self) -> None:
        text = "\x1b[1mBold\x1b[0m \x1b[2mDim\x1b[0m"
        assert strip_ansi(text) == "Bold Dim"

    def test_passes_plain_text(self) -> None:
        assert strip_ansi("no escapes here") == "no escapes here"

    def test_passes_unicode_emojis(self) -> None:
        assert strip_ansi("📁 ~/project") == "📁 ~/project"


class TestBarsToUnicode:
    """Verify that ANSI space-bar patterns are converted to block characters."""

    def _make_bar(self, filled: int, empty: int) -> str:
        """Build the exact byte sequence that render_bar() emits."""
        filled_part = f"\x1b[48;2;0;160;0m{' ' * filled}\x1b[0m"
        empty_part = f"\x1b[48;2;60;60;60m{' ' * empty}\x1b[0m"
        return filled_part + empty_part

    def test_full_bar(self) -> None:
        bar = self._make_bar(10, 0)
        result = _bars_to_unicode(bar)
        assert result == "█" * 10

    def test_empty_bar(self) -> None:
        bar = self._make_bar(0, 10)
        result = _bars_to_unicode(bar)
        assert result == "░" * 10

    def test_partial_bar(self) -> None:
        bar = self._make_bar(6, 4)
        result = _bars_to_unicode(bar)
        assert result == "██████░░░░"

    def test_unrelated_ansi_not_touched(self) -> None:
        text = "\x1b[38;2;46;149;153mtext\x1b[0m"
        # Should not match bar pattern; text unchanged
        assert _bars_to_unicode(text) == text


class TestConvertForDiscord:
    def test_bars_become_unicode_blocks(self) -> None:
        bar = "\x1b[48;2;0;160;0m      \x1b[0m\x1b[48;2;60;60;60m    \x1b[0m"
        result = convert_for_discord(bar)
        assert result == "██████░░░░"
        assert "\x1b" not in result

    def test_colour_and_bar_both_stripped(self) -> None:
        text = "\x1b[38;2;0;160;0m62%\x1b[0m"
        bar = "\x1b[48;2;0;160;0m   \x1b[0m\x1b[48;2;60;60;60m   \x1b[0m"
        result = convert_for_discord(bar + " " + text)
        assert result == "███░░░ 62%"


class TestBuildStatuslineJson:
    def test_output_is_valid_json(self) -> None:
        raw = build_statusline_json(
            cwd="/home/user/project",
            model_id="sonnet",
            model_display_name="Claude Sonnet 4.6",
            context_size=200000,
            input_tokens=12000,
            cache_creation_tokens=500,
            cache_read_tokens=3000,
        )
        data = json.loads(raw)
        assert data["workspace"]["current_dir"] == "/home/user/project"
        assert data["model"]["id"] == "sonnet"
        assert data["model"]["display_name"] == "Claude Sonnet 4.6"
        assert data["context_window"]["context_window_size"] == 200000
        assert data["context_window"]["current_usage"]["input_tokens"] == 12000

    def test_cache_tokens_mapped_correctly(self) -> None:
        raw = build_statusline_json(
            cwd="/",
            model_id="x",
            model_display_name="x",
            context_size=1,
            input_tokens=0,
            cache_creation_tokens=111,
            cache_read_tokens=222,
        )
        data = json.loads(raw)
        usage = data["context_window"]["current_usage"]
        assert usage["cache_creation_input_tokens"] == 111
        assert usage["cache_read_input_tokens"] == 222


# ---------------------------------------------------------------------------
# I/O tests — settings file reading
# ---------------------------------------------------------------------------


class TestReadStatuslineCommand:
    def test_reads_command_type(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps({"statusLine": {"type": "command", "command": "bash ~/my-statusline.sh"}})
        )
        assert read_statusline_command(str(settings)) == "bash ~/my-statusline.sh"

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert read_statusline_command(str(tmp_path / "nonexistent.json")) is None

    def test_returns_none_when_type_not_command(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"statusLine": {"type": "text", "value": "hi"}}))
        assert read_statusline_command(str(settings)) is None

    def test_returns_none_when_no_statusline_key(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"model": "sonnet"}))
        assert read_statusline_command(str(settings)) is None

    def test_returns_none_on_invalid_json(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("{not valid json}")
        assert read_statusline_command(str(settings)) is None

    def test_accepts_lowercase_statusline_key(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"statusline": {"type": "command", "command": "echo hi"}}))
        assert read_statusline_command(str(settings)) == "echo hi"


# ---------------------------------------------------------------------------
# Async tests — render_statusline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRenderStatusline:
    async def test_returns_plain_text_from_command(self) -> None:
        result = await render_statusline("echo '📁 ~/project'", "{}", timeout=5.0)
        assert result == "📁 ~/project"

    async def test_strips_ansi_from_output(self) -> None:
        cmd = r"printf '\033[38;2;0;160;0mGreen text\033[0m\n'"
        result = await render_statusline(cmd, "{}", timeout=5.0)
        assert result == "Green text"
        assert "\x1b" not in (result or "")

    async def test_returns_none_on_empty_output(self) -> None:
        result = await render_statusline("true", "{}", timeout=5.0)
        assert result is None

    async def test_returns_none_on_timeout(self) -> None:
        result = await render_statusline("sleep 10", "{}", timeout=0.1)
        assert result is None

    async def test_returns_none_on_missing_command(self) -> None:
        result = await render_statusline("this_command_does_not_exist_xyz", "{}", timeout=2.0)
        assert result is None

    async def test_bar_converted_to_unicode_blocks(self) -> None:
        # The statusline script outputs bars as ANSI-coloured spaces.
        # Verify that render_statusline converts them before returning.
        filled = "\x1b[48;2;0;160;0m    \x1b[0m"
        empty = "\x1b[48;2;60;60;60m    \x1b[0m"
        cmd = f"printf '{filled}{empty}\\n'"
        result = await render_statusline(cmd, "{}", timeout=5.0)
        assert result == "████░░░░"
