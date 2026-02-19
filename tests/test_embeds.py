"""Tests for Discord embed builders."""

from __future__ import annotations

from claude_discord.discord_ui.embeds import session_complete_embed, thinking_embed


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
