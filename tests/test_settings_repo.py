"""Tests for SettingsRepository — key-value bot settings persistence."""

from __future__ import annotations

import pytest

from claude_discord.database.models import init_db
from claude_discord.database.settings_repo import SettingsRepository


@pytest.fixture
async def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return SettingsRepository(db_path)


class TestSettingsRepository:
    async def test_get_returns_none_for_missing_key(self, repo):
        result = await repo.get("nonexistent")
        assert result is None

    async def test_get_returns_default_for_missing_key(self, repo):
        result = await repo.get("nonexistent", default="fallback")
        assert result == "fallback"

    async def test_set_and_get(self, repo):
        await repo.set("sync_thread_style", "message")
        result = await repo.get("sync_thread_style")
        assert result == "message"

    async def test_set_overwrites_existing(self, repo):
        await repo.set("sync_thread_style", "message")
        await repo.set("sync_thread_style", "channel")
        result = await repo.get("sync_thread_style")
        assert result == "channel"

    async def test_delete(self, repo):
        await repo.set("key", "value")
        deleted = await repo.delete("key")
        assert deleted is True
        assert await repo.get("key") is None

    async def test_delete_nonexistent(self, repo):
        deleted = await repo.delete("nonexistent")
        assert deleted is False

    async def test_get_all(self, repo):
        await repo.set("a", "1")
        await repo.set("b", "2")
        all_settings = await repo.get_all()
        assert all_settings == {"a": "1", "b": "2"}

    async def test_get_all_empty(self, repo):
        all_settings = await repo.get_all()
        assert all_settings == {}

    async def test_get_default_backend_uses_fallback_when_missing(self, repo):
        result = await repo.get_default_backend(fallback="codex")
        assert result == "codex"

    async def test_set_default_backend_normalizes_and_persists(self, repo):
        await repo.set_default_backend("Codex")
        assert await repo.get("default_backend") == "codex"

    async def test_get_default_backend_ignores_invalid_stored_value(self, repo):
        await repo.set("default_backend", "wat")
        result = await repo.get_default_backend(fallback="claude")
        assert result == "claude"
