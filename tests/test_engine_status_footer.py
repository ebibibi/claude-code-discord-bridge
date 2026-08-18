"""Tests for _post_engine_status_footer (Claude statusLine + Codex line gating)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite

from claude_discord.backend_settings import BackendSettings
from claude_discord.cogs.event_processor import _post_engine_status_footer
from claude_discord.database.settings_repo import SettingsRepository

_EP = "claude_discord.cogs.event_processor"
_ES = "claude_discord.discord_ui.engine_status"


async def _settings(mode: str) -> BackendSettings:
    tmp = Path(tempfile.mkdtemp()) / "settings.db"
    async with aiosqlite.connect(str(tmp)) as db:
        await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await db.commit()
    s = BackendSettings(
        SettingsRepository(str(tmp)),
        env_backend="claude",
        env_model_for_claude="sonnet",
        env_model_for_codex="",
    )
    await s.set_codex_status_mode(mode)
    return s


async def _run(*, backend: str, mode: str, codex_line, statusline) -> str | None:
    thread = AsyncMock()
    settings = await _settings(mode)
    with (
        patch(f"{_ES}.get_codex_status_line", AsyncMock(return_value=codex_line)),
        patch(f"{_EP}._render_claude_statusline_text", AsyncMock(return_value=statusline)),
    ):
        await _post_engine_status_footer(
            thread,
            backend=backend,
            working_dir="/tmp",
            model="sonnet",
            context_window=200000,
            input_tokens=100,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            api_label="Anthropic API (direct)",
            backend_settings=settings,
            codex_command="codex",
            thread_id=1,
        )
    if thread.send.await_count == 0:
        return None
    return thread.send.await_args.args[0]


class TestGating:
    async def test_off_claude_turn_shows_only_claude(self) -> None:
        body = await _run(
            backend="claude", mode="off", codex_line="🤖 Codex: x", statusline="Ctx 4%"
        )
        assert body is not None
        assert "Codex" not in body
        assert "Ctx 4%" in body
        assert "API:" in body

    async def test_auto_claude_turn_shows_both(self) -> None:
        body = await _run(
            backend="claude", mode="auto", codex_line="🤖 Codex: 5h 1%", statusline="Ctx 4%"
        )
        assert body is not None
        assert "Codex: 5h 1%" in body
        assert "Ctx 4%" in body

    async def test_auto_codex_turn_no_api_label_but_shows_codex(self) -> None:
        body = await _run(
            backend="codex", mode="auto", codex_line="🤖 Codex: 5h 1%", statusline="Ctx 0%"
        )
        assert body is not None
        assert "Codex: 5h 1%" in body
        # API label is Claude-specific; suppressed on codex turns.
        assert "API:" not in body

    async def test_auto_codex_turn_fetch_fails_posts_nothing(self) -> None:
        body = await _run(backend="codex", mode="auto", codex_line=None, statusline=None)
        assert body is None

    async def test_off_codex_turn_posts_nothing(self) -> None:
        body = await _run(
            backend="codex", mode="off", codex_line="🤖 Codex: x", statusline="Ctx 0%"
        )
        assert body is None

    async def test_no_settings_means_off(self) -> None:
        thread = AsyncMock()
        with (
            patch(f"{_ES}.get_codex_status_line", AsyncMock(return_value="🤖 Codex: x")),
            patch(f"{_EP}._render_claude_statusline_text", AsyncMock(return_value=None)),
        ):
            await _post_engine_status_footer(
                thread,
                backend="codex",
                working_dir="/tmp",
                model="gpt-5.4",
                context_window=None,
                input_tokens=None,
                cache_creation_tokens=None,
                cache_read_tokens=None,
                api_label="OpenAI",
                backend_settings=None,
                codex_command="codex",
                thread_id=1,
            )
        assert thread.send.await_count == 0
