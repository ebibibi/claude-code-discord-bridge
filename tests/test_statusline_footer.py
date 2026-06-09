"""Tests for _post_statusline_footer.

The footer now always surfaces the current API provider line (when known),
even if no ``statusLine`` is configured, and appends the statusLine output
below it when present.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from claude_discord.cogs.event_processor import _post_statusline_footer

_STATUSLINE_MOD = "claude_discord.discord_ui.statusline"
_CODEX_USAGE_MOD = "claude_discord.discord_ui.codex_usage"


async def test_posts_api_line_when_no_statusline_configured() -> None:
    thread = AsyncMock()
    with patch(f"{_STATUSLINE_MOD}.read_statusline_command", return_value=None):
        await _post_statusline_footer(
            thread=thread,
            working_dir=None,
            model="opus",
            context_window=None,
            input_tokens=None,
            cache_creation_tokens=None,
            cache_read_tokens=None,
            api_label="Anthropic API (direct)",
        )
    thread.send.assert_awaited_once()
    body = thread.send.await_args.args[0]
    assert "API: Anthropic API (direct)" in body


async def test_no_post_when_neither_api_label_nor_statusline() -> None:
    thread = AsyncMock()
    with patch(f"{_STATUSLINE_MOD}.read_statusline_command", return_value=None):
        await _post_statusline_footer(
            thread=thread,
            working_dir=None,
            model="opus",
            context_window=None,
            input_tokens=None,
            cache_creation_tokens=None,
            cache_read_tokens=None,
            api_label=None,
        )
    thread.send.assert_not_awaited()


async def test_combines_api_line_and_statusline_output() -> None:
    thread = AsyncMock()
    with (
        patch(f"{_STATUSLINE_MOD}.read_statusline_command", return_value="cmd"),
        patch(
            f"{_STATUSLINE_MOD}.render_statusline",
            new=AsyncMock(return_value="Ctx 45% | quota OK"),
        ),
    ):
        await _post_statusline_footer(
            thread=thread,
            working_dir=None,
            model="opus",
            context_window=200000,
            input_tokens=1000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            api_label="Azure AI Foundry (jbs-llm-platform)",
        )
    body = thread.send.await_args.args[0]
    assert "API: Azure AI Foundry (jbs-llm-platform)" in body
    assert "Ctx 45%" in body
    # The API line should appear above the statusline output.
    assert body.index("API:") < body.index("Ctx 45%")


async def test_posts_codex_usage_footer() -> None:
    thread = AsyncMock()
    with (
        patch(
            f"{_CODEX_USAGE_MOD}.fetch_codex_rate_limits",
            new=AsyncMock(
                return_value={
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 24,
                            "windowDurationMins": 300,
                            "resetsAt": 4_102_444_800,
                        },
                        "secondary": {
                            "usedPercent": 11,
                            "windowDurationMins": 10080,
                            "resetsAt": 4_102_531_200,
                        },
                    }
                }
            ),
        ),
    ):
        await _post_statusline_footer(
            thread=thread,
            working_dir=None,
            model="gpt-5.5",
            context_window=None,
            input_tokens=None,
            cache_creation_tokens=None,
            cache_read_tokens=None,
            api_label="OpenAI API (direct)",
            backend="codex",
            command="codex",
        )
    body = thread.send.await_args.args[0]
    assert "API: OpenAI API (direct)" in body
    assert "5h" in body
    assert "7d" in body
