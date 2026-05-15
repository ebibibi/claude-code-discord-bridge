"""Tests for BackendSettings (resolution + persistence)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import aiosqlite
import pytest

from claude_discord.backend_settings import (
    BACKEND_GLOBAL,
    BackendSettings,
)
from claude_discord.database.settings_repo import SettingsRepository


async def _new_repo() -> tuple[SettingsRepository, Path]:
    """Create a fresh on-disk SettingsRepository with the schema created."""
    tmp = Path(tempfile.mkdtemp()) / "settings.db"
    async with aiosqlite.connect(str(tmp)) as db:
        await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await db.commit()
    return SettingsRepository(str(tmp)), tmp


class TestResolution:
    async def test_global_only_env_fallback(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        assert await s.current_backend() == "claude"
        assert await s.current_model("claude") == "sonnet"
        assert await s.current_model("codex") is None

    async def test_global_set_overrides_env(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await s.set_backend("codex")
        assert await s.current_backend() == "codex"

    async def test_thread_overrides_global(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await s.set_backend("claude")
        await s.set_backend("codex", thread_id=42)
        assert await s.current_backend() == "claude"
        assert await s.current_backend(thread_id=42) == "codex"

    async def test_model_thread_overrides_global(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await s.set_model("claude", "opus")
        await s.set_model("claude", "haiku", thread_id=99)
        assert await s.current_model("claude") == "opus"
        assert await s.current_model("claude", thread_id=99) == "haiku"
        # other thread sees global
        assert await s.current_model("claude", thread_id=1) == "opus"

    async def test_unknown_backend_in_db_falls_through(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="",
            env_model_for_codex="",
        )
        # Inject a corrupted value directly
        await repo.set(BACKEND_GLOBAL, "bogus")
        assert await s.current_backend() == "claude"

    async def test_clear_thread_overrides(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await s.set_backend("codex", thread_id=7)
        await s.set_model("codex", "gpt-5", thread_id=7)
        deleted = await s.clear_thread_overrides(7)
        assert deleted == 2
        assert await s.current_backend(thread_id=7) == "claude"


class TestMutationValidation:
    async def test_set_backend_rejects_unknown(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="",
            env_model_for_codex="",
        )
        with pytest.raises(ValueError):
            await s.set_backend("gpt4")  # type: ignore[arg-type]

    async def test_set_model_rejects_empty(self) -> None:
        repo, _ = await _new_repo()
        s = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="",
            env_model_for_codex="",
        )
        with pytest.raises(ValueError):
            await s.set_model("claude", "")
