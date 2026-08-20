"""Tests for SettingsRepository — key-value bot settings persistence."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from claude_discord.database.models import init_db
from claude_discord.database.settings_repo import SettingsRepository


@pytest.fixture
async def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return SettingsRepository(db_path)


class TestSettingsRepository:
    async def test_get_remains_available_during_an_exclusive_write(self, tmp_path):
        """Readers should see the last commit while another connection writes."""
        db_path = str(tmp_path / "concurrent.db")
        await init_db(db_path)
        repo = SettingsRepository(db_path)
        await repo.set("claude_model", "committed-model")

        writer = await aiosqlite.connect(db_path)
        try:
            await writer.execute("BEGIN EXCLUSIVE")
            await writer.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                ("uncommitted-model", "claude_model"),
            )

            value = await asyncio.wait_for(repo.get("claude_model"), timeout=0.5)
        finally:
            await writer.rollback()
            await writer.close()

        assert value == "committed-model"

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
