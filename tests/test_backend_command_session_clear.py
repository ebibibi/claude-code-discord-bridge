"""Tests for BackendCommandCog clear-thread-session-on-backend-change."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord

from claude_discord.backend_factory import BackendFactory
from claude_discord.backend_settings import BackendSettings
from claude_discord.cogs.backend_command import BackendCommandCog
from claude_discord.database.repository import SessionRecord
from claude_discord.database.settings_repo import SettingsRepository

# Sentinel: the thread has no stored session record at all.
_NO_RECORD = object()


async def _new_settings_repo() -> SettingsRepository:
    tmp = Path(tempfile.mkdtemp()) / "settings.db"
    async with aiosqlite.connect(str(tmp)) as db:
        await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await db.commit()
    return SettingsRepository(str(tmp))


def _make_cog(
    settings: BackendSettings, session_backend: str | None | object = _NO_RECORD
) -> BackendCommandCog:
    bot = MagicMock()
    factory = BackendFactory(
        claude_command="claude",
        codex_command="codex",
        permission_mode="acceptEdits",
        working_dir=None,
        timeout_seconds=300,
        dangerously_skip_permissions=False,
        allowed_tools=None,
        append_system_prompt=None,
        effort=None,
    )
    chat_cog = MagicMock()
    chat_cog.runner = MagicMock()
    chat_cog.runner.model = "sonnet"
    chat_cog.repo = MagicMock()
    chat_cog.repo.delete = AsyncMock(return_value=True)
    record = (
        None
        if session_backend is _NO_RECORD
        else SessionRecord(
            thread_id=42,
            session_id="sess-1",
            working_dir=None,
            model=None,
            origin="discord",
            summary=None,
            created_at="",
            last_used_at="",
            backend=session_backend,  # type: ignore[arg-type]
        )
    )
    chat_cog.repo.get = AsyncMock(return_value=record)
    cog = BackendCommandCog(bot, settings=settings, factory=factory, chat_cog=chat_cog)
    return cog


def _make_thread_interaction(thread_id: int) -> MagicMock:
    interaction = MagicMock()
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    interaction.channel = thread
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


class TestBackendCommandClearsSession:
    """When /backend changes a thread's effective backend, the stored session
    must be cleared so Codex doesn't try to resume a Claude session id (or
    vice versa)."""

    async def test_clears_session_on_thread_backend_change(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _make_cog(settings)
        interaction = _make_thread_interaction(thread_id=42)

        # Run /backend codex scope:thread on a thread defaulting to claude.
        await cog.backend_command.callback(cog, interaction, name="codex", scope="thread")

        # The session for thread 42 should have been wiped.
        cog._chat_cog.repo.delete.assert_awaited_once_with(42)

    async def test_no_clear_when_backend_is_same(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        # Thread is already on claude.
        await settings.set_backend("claude", thread_id=42)
        cog = _make_cog(settings)
        interaction = _make_thread_interaction(thread_id=42)

        # Setting it to claude again should not wipe the session.
        await cog.backend_command.callback(cog, interaction, name="claude", scope="thread")

        cog._chat_cog.repo.delete.assert_not_awaited()

    async def test_clears_session_when_switching_back(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=42)
        cog = _make_cog(settings)
        interaction = _make_thread_interaction(thread_id=42)

        # Now switching back to claude should also wipe.
        await cog.backend_command.callback(cog, interaction, name="claude", scope="thread")

        cog._chat_cog.repo.delete.assert_awaited_once_with(42)

    async def test_keeps_session_owned_by_the_target_backend(self) -> None:
        """Switching *to* the backend that minted the stored session keeps it.

        This is the recovery path for a thread whose session was stranded by a
        global backend switch: the Codex rollout is still on disk, so pointing
        the thread back at Codex must resume it, not wipe it.
        """
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _make_cog(settings, session_backend="codex")
        interaction = _make_thread_interaction(thread_id=42)

        await cog.backend_command.callback(cog, interaction, name="codex", scope="thread")

        cog._chat_cog.repo.delete.assert_not_awaited()

    async def test_global_change_does_not_clear_any_thread_session(self) -> None:
        """A global /backend change must not wipe individual threads' sessions
        (they may have explicit thread overrides). It only swaps the default
        runner that fresh threads inherit."""
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _make_cog(settings)
        # No thread in the interaction (global scope by definition).
        interaction = MagicMock()
        interaction.channel = MagicMock()  # NOT a discord.Thread
        # Force not-a-thread by spec-less mock + isinstance check returning False.
        # Easiest: skip channel handling and call with explicit scope.
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.backend_command.callback(cog, interaction, name="codex", scope="global")

        # Global change → no thread session deletes.
        cog._chat_cog.repo.delete.assert_not_awaited()
