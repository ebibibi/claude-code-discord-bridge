"""Tests for thread_renamer — auto-title suggestion via claude -p."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_discord.discord_ui.thread_renamer import suggest_title

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(stdout: bytes, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.kill = MagicMock()
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Normal cases
# ---------------------------------------------------------------------------


class TestSuggestTitleNormal:
    @pytest.mark.asyncio
    async def test_returns_title_from_claude(self):
        proc = _make_proc(b"Fix authentication bug\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await suggest_title("Help me fix the login system")
        assert result == "Fix authentication bug"

    @pytest.mark.asyncio
    async def test_strips_surrounding_whitespace(self):
        proc = _make_proc(b"  Refactor database layer  \n")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await suggest_title("Please refactor the DB code")
        assert result == "Refactor database layer"

    @pytest.mark.asyncio
    async def test_strips_surrounding_quotes(self):
        # Some models wrap the title in quotes
        proc = _make_proc(b'"Add dark mode support"\n')
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await suggest_title("Add dark mode")
        assert result == "Add dark mode support"

    @pytest.mark.asyncio
    async def test_truncates_to_90_chars(self):
        long_title = "A" * 100
        proc = _make_proc(long_title.encode())
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await suggest_title("some request")
        assert result is not None
        assert len(result) <= 90

    @pytest.mark.asyncio
    async def test_uses_custom_claude_command(self):
        proc = _make_proc(b"Custom command title\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await suggest_title("request", claude_command="/usr/local/bin/claude")
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "/usr/local/bin/claude"

    @pytest.mark.asyncio
    async def test_prompt_contains_user_message(self):
        proc = _make_proc(b"Some Title\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await suggest_title("please help me with authentication")
        # The prompt argument (3rd positional arg) should contain the message
        prompt_arg = mock_exec.call_args[0][2]
        assert "please help me with authentication" in prompt_arg


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSuggestTitleEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_message_returns_none(self):
        result = await suggest_title("")
        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_only_message_returns_none(self):
        result = await suggest_title("   \n  ")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_claude_output_returns_none(self):
        proc = _make_proc(b"")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await suggest_title("some request")
        assert result is None

    @pytest.mark.asyncio
    async def test_long_input_message_is_truncated_before_sending(self):
        """Very long messages should be truncated in the prompt."""
        proc = _make_proc(b"Title\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await suggest_title("X" * 5000)
        prompt_arg = mock_exec.call_args[0][2]
        # The embedded message portion should not exceed 2000 chars
        assert len(prompt_arg) < 3000


# ---------------------------------------------------------------------------
# Error / timeout handling
# ---------------------------------------------------------------------------


class TestSuggestTitleErrors:
    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        proc = _make_proc(b"Title\n")

        async def _hang(*_args, **_kwargs):
            raise TimeoutError

        proc.communicate = _hang
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await suggest_title("some request")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_subprocess_exception(self):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("claude not found"),
        ):
            result = await suggest_title("some request")
        assert result is None

    @pytest.mark.asyncio
    async def test_kills_process_on_timeout(self):
        proc = _make_proc(b"Title\n")

        async def _hang(*_args, **_kwargs):
            raise TimeoutError

        proc.communicate = _hang
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await suggest_title("some request")
        proc.kill.assert_called_once()
