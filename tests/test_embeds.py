"""Tests for Discord embed builders."""

from __future__ import annotations

from claude_discord.claude.types import ToolCategory, ToolUseEvent
from claude_discord.discord_ui.embeds import (
    redacted_thinking_embed,
    session_complete_embed,
    thinking_embed,
    tool_result_embed,
    tool_use_embed,
)


class TestThinkingEmbed:
    def test_description_uses_plain_code_block(self) -> None:
        """Thinking embed must use a plain code block (no spoiler) for guaranteed readability.

        spoiler+code block (||```text```||) does not apply code block styling
        when revealed inside Discord embed descriptions — the embed accent color
        bleeds into the revealed text, making it unreadable.
        """
        embed = thinking_embed("Let me think about this.")
        assert embed.description is not None
        assert embed.description.startswith("```\n")
        assert embed.description.endswith("\n```")
        assert "||" not in embed.description

    def test_thinking_text_preserved(self) -> None:
        """Original thinking text should appear inside the code block."""
        text = "Step 1: analyze. Step 2: respond."
        embed = thinking_embed(text)
        assert text in embed.description

    def test_long_text_truncated(self) -> None:
        """Text exceeding the limit should be truncated with a notice."""
        long_text = "x" * 5000
        embed = thinking_embed(long_text)
        assert len(embed.description) <= 4096
        assert "(truncated)" in embed.description

    def test_short_text_not_truncated(self) -> None:
        """Short text should not be modified."""
        text = "Brief thought."
        embed = thinking_embed(text)
        assert "(truncated)" not in embed.description
        assert text in embed.description

    def test_title(self) -> None:
        """Embed should have the Thinking title."""
        embed = thinking_embed("x")
        assert embed.title is not None
        assert "Thinking" in embed.title


class TestSessionCompleteEmbed:
    def test_shows_tokens_when_provided(self) -> None:
        embed = session_complete_embed(input_tokens=1000, output_tokens=500)
        assert embed.description is not None
        assert "1.0k" in embed.description
        assert "500" in embed.description

    def test_shows_cache_hit_percentage(self) -> None:
        embed = session_complete_embed(input_tokens=700, output_tokens=100, cache_read_tokens=300)
        assert embed.description is not None
        assert "%" in embed.description

    def test_no_tokens_omits_token_line(self) -> None:
        embed = session_complete_embed(cost_usd=0.01)
        assert embed.description is not None
        assert "📊" not in embed.description

    def test_zero_cache_omits_cache_pct(self) -> None:
        embed = session_complete_embed(input_tokens=500, output_tokens=100, cache_read_tokens=0)
        assert embed.description is not None
        assert "%" not in embed.description


class TestSessionCompleteContextUsage:
    """Tests for context usage display in session complete embed."""

    def test_context_usage_shown(self) -> None:
        # Output tokens are NOT counted — only input tokens determine context usage.
        embed = session_complete_embed(
            input_tokens=100000,
            output_tokens=5000,
            context_window=200000,
        )
        assert embed.description is not None
        # 100000 / 200000 = 50% (output_tokens excluded)
        assert "50% ctx" in embed.description

    def test_context_usage_shows_remaining_until_compact(self) -> None:
        embed = session_complete_embed(
            input_tokens=100000,
            output_tokens=5000,
            context_window=200000,
        )
        assert embed.description is not None
        # 50% used → AUTOCOMPACT_THRESHOLD(83.5) - 50 = 33.5 → 34% until compact
        assert "until compact" in embed.description

    def test_context_usage_with_cache(self) -> None:
        # cache_read_tokens counts toward context; output_tokens do not.
        embed = session_complete_embed(
            input_tokens=50000,
            output_tokens=5000,
            cache_read_tokens=100000,
            context_window=200000,
        )
        assert embed.description is not None
        # (50000 + 100000) / 200000 = 75% (output_tokens excluded)
        assert "75% ctx" in embed.description

    def test_context_usage_includes_cache_creation(self) -> None:
        # cache_creation_tokens also count toward context usage.
        embed = session_complete_embed(
            input_tokens=50000,
            output_tokens=5000,
            cache_creation_tokens=50000,
            context_window=200000,
        )
        assert embed.description is not None
        # (50000 + 50000) / 200000 = 50%
        assert "50% ctx" in embed.description

    def test_output_tokens_do_not_affect_context_pct(self) -> None:
        """Output tokens must be excluded from context window calculation."""
        embed_small = session_complete_embed(
            input_tokens=50000,
            output_tokens=100,
            context_window=200000,
        )
        embed_large = session_complete_embed(
            input_tokens=50000,
            output_tokens=100000,
            context_window=200000,
        )
        # Both should show the same context % regardless of output size
        assert embed_small.description is not None
        assert embed_large.description is not None
        assert "25% ctx" in embed_small.description
        assert "25% ctx" in embed_large.description

    def test_context_usage_capped_at_100_percent(self) -> None:
        """Context % must never exceed 100% even with very large token counts."""
        embed = session_complete_embed(
            input_tokens=500000,
            output_tokens=0,
            context_window=200000,
        )
        assert embed.description is not None
        assert "100% ctx" in embed.description

    def test_autocompact_warning_when_above_threshold(self) -> None:
        # 170000 / 200000 = 85% > 83.5% threshold → footer warning
        embed = session_complete_embed(
            input_tokens=170000,
            output_tokens=5000,
            context_window=200000,
        )
        assert embed.footer is not None
        assert "auto-compact" in embed.footer.text

    def test_above_threshold_shows_warning_icon_in_description(self) -> None:
        embed = session_complete_embed(
            input_tokens=170000,
            output_tokens=5000,
            context_window=200000,
        )
        assert embed.description is not None
        # Should show ⚠️ in the description line instead of "until compact"
        assert "⚠️" in embed.description
        assert "until compact" not in embed.description

    def test_no_warning_below_threshold(self) -> None:
        embed = session_complete_embed(
            input_tokens=50000,
            output_tokens=5000,
            context_window=200000,
        )
        assert embed.footer is None or embed.footer.text is None

    def test_no_context_info_without_context_window(self) -> None:
        embed = session_complete_embed(
            input_tokens=50000,
            output_tokens=5000,
        )
        assert "% ctx" not in (embed.description or "")


class TestToolUseEmbed:
    """Tests for tool_use_embed elapsed time display."""

    def _bash_tool(self) -> ToolUseEvent:
        return ToolUseEvent(
            tool_id="t1",
            tool_name="Bash",
            tool_input={"command": "az login --use-device-code"},
            category=ToolCategory.COMMAND,
        )

    def test_in_progress_without_elapsed(self) -> None:
        embed = tool_use_embed(self._bash_tool(), in_progress=True)
        assert embed.title is not None
        assert embed.title.endswith("...")
        assert embed.description is None  # no elapsed → no description

    def test_in_progress_with_elapsed_shows_description(self) -> None:
        """Elapsed time appears in description, leaving the title stable."""
        embed = tool_use_embed(self._bash_tool(), in_progress=True, elapsed_s=42)
        assert embed.title is not None
        assert embed.title.endswith("...")
        # Title must NOT contain the elapsed time (keeps it stable across ticks)
        assert "42s" not in embed.title
        # Description carries the elapsed time
        assert embed.description is not None
        assert "42s" in embed.description

    def test_completed_no_ellipsis(self) -> None:
        embed = tool_use_embed(self._bash_tool(), in_progress=False)
        assert embed.title is not None
        assert not embed.title.endswith("...")

    def test_completed_ignores_elapsed(self) -> None:
        """elapsed_s has no effect when in_progress=False."""
        embed = tool_use_embed(self._bash_tool(), in_progress=False, elapsed_s=99)
        assert embed.title is not None
        assert "99s" not in embed.title
        assert embed.description is None

    def test_title_stable_across_ticks(self) -> None:
        """Title must be identical at t=0, t=10, t=20 so Discord doesn't re-render it."""
        base = tool_use_embed(self._bash_tool(), in_progress=True)
        tick1 = tool_use_embed(self._bash_tool(), in_progress=True, elapsed_s=10)
        tick2 = tool_use_embed(self._bash_tool(), in_progress=True, elapsed_s=20)
        assert base.title == tick1.title == tick2.title

    def test_title_within_discord_limit(self) -> None:
        """Even with a very long command name, title should be capped at 256 chars."""
        long_tool = ToolUseEvent(
            tool_id="t2",
            tool_name="Bash",
            tool_input={"command": "x" * 200},
            category=ToolCategory.COMMAND,
        )
        embed = tool_use_embed(long_tool, in_progress=True, elapsed_s=120)
        assert len(embed.title) <= 256


class TestToolResultEmbed:
    """Tests for tool_result_embed — uses description for generous output display."""

    def test_result_in_description_not_field(self) -> None:
        """Result content must be in description (4096 limit) not a field (1024 limit)."""
        embed = tool_result_embed("🔧 Running: ls...", "file1\nfile2\nfile3")
        assert embed.description is not None
        assert "file1" in embed.description
        assert len(embed.fields) == 0  # no fields

    def test_result_wrapped_in_code_block(self) -> None:
        embed = tool_result_embed("🔧 Running: ls...", "output here")
        assert embed.description is not None
        assert embed.description.startswith("```")
        assert embed.description.endswith("```")

    def test_title_strips_trailing_dots(self) -> None:
        """The '...' suffix from the in-progress title should be stripped."""
        embed = tool_result_embed("🔧 Running: ls...", "ok")
        assert embed.title is not None
        assert not embed.title.endswith(".")

    def test_30_lines_fit_without_truncation(self) -> None:
        """30 lines of typical output should display in full."""
        lines = [f"Step {i:02d}/30 — output text here" for i in range(1, 31)]
        content = "\n".join(lines)
        embed = tool_result_embed("🔧 Running: cmd...", content)
        assert embed.description is not None
        for line in lines:
            assert line in embed.description

    def test_empty_result_no_description(self) -> None:
        embed = tool_result_embed("🔧 Running: ls...", "")
        assert embed.description is None


class TestRedactedThinkingEmbed:
    def test_title_mentions_redacted(self) -> None:
        embed = redacted_thinking_embed()
        assert embed.title is not None
        assert "redacted" in embed.title.lower()

    def test_has_description(self) -> None:
        embed = redacted_thinking_embed()
        assert embed.description is not None
        assert len(embed.description) > 0

    def test_color_distinct_from_regular_thinking(self) -> None:
        regular = thinking_embed("x")
        redacted = redacted_thinking_embed()
        assert redacted.colour.value != regular.colour.value
