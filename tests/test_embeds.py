"""Tests for Discord embed builders."""

from __future__ import annotations

from claude_discord.claude.types import ToolCategory, ToolUseEvent
from claude_discord.discord_ui.embeds import (
    redacted_thinking_embed,
    session_complete_embed,
    thinking_embed,
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
        assert "(" not in embed.title  # no elapsed time shown

    def test_in_progress_with_elapsed(self) -> None:
        embed = tool_use_embed(self._bash_tool(), in_progress=True, elapsed_s=42)
        assert embed.title is not None
        assert "(42s)" in embed.title
        assert embed.title.endswith("...")

    def test_completed_no_ellipsis(self) -> None:
        embed = tool_use_embed(self._bash_tool(), in_progress=False)
        assert embed.title is not None
        assert not embed.title.endswith("...")

    def test_completed_ignores_elapsed(self) -> None:
        """elapsed_s has no effect when in_progress=False."""
        embed = tool_use_embed(self._bash_tool(), in_progress=False, elapsed_s=99)
        assert embed.title is not None
        assert "99s" not in embed.title

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
