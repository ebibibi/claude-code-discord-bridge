"""Tests for ContextLinksCog — project-aware context link posting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs.context_links import (
    ContextLinksCog,
    build_context_embed,
    build_obsidian_uri,
    load_config,
    match_project,
)

# ---------------------------------------------------------------------------
# Pure function tests: build_obsidian_uri
# ---------------------------------------------------------------------------


class TestBuildObsidianUri:
    def test_basic_ascii_path(self) -> None:
        uri = build_obsidian_uri("MyVault", "Projects/ccdb/status.md")
        assert uri == "obsidian://open?vault=MyVault&file=Projects%2Fccdb%2Fstatus.md"

    def test_unicode_path(self) -> None:
        uri = build_obsidian_uri("obsidian", "02_Contexts/個人開発/ccdb/status.md")
        assert "vault=obsidian" in uri
        assert "file=" in uri
        assert "obsidian://open?" in uri

    def test_empty_vault_name(self) -> None:
        uri = build_obsidian_uri("", "path.md")
        assert "vault=" in uri

    def test_path_with_spaces(self) -> None:
        uri = build_obsidian_uri("vault", "My Notes/project a/status.md")
        assert "My%20Notes" in uri or "My+Notes" in uri


# ---------------------------------------------------------------------------
# Pure function tests: load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_valid_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "context_links.json"
        config_data = {
            "obsidian_vault": "obsidian",
            "projects": [
                {
                    "match": ["ccdb", "discord bot"],
                    "links": [
                        {"label": "Status", "obsidian": "Projects/ccdb/status.md"},
                        {"label": "GitHub", "url": "https://github.com/example/ccdb"},
                    ],
                }
            ],
        }
        config_file.write_text(json.dumps(config_data))
        result = load_config(str(config_file))
        assert result is not None
        assert result["obsidian_vault"] == "obsidian"
        assert len(result["projects"]) == 1

    def test_missing_file_returns_none(self) -> None:
        result = load_config("/nonexistent/path/context_links.json")
        assert result is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        config_file = tmp_path / "bad.json"
        config_file.write_text("not valid json {{{")
        result = load_config(str(config_file))
        assert result is None

    def test_missing_projects_key_returns_none(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty.json"
        config_file.write_text(json.dumps({"obsidian_vault": "test"}))
        result = load_config(str(config_file))
        assert result is None

    def test_empty_projects_returns_none(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty_projects.json"
        config_file.write_text(json.dumps({"projects": []}))
        result = load_config(str(config_file))
        assert result is None


# ---------------------------------------------------------------------------
# Pure function tests: match_project
# ---------------------------------------------------------------------------


class TestMatchProject:
    @pytest.fixture()
    def sample_config(self) -> dict[str, Any]:
        return {
            "obsidian_vault": "obsidian",
            "projects": [
                {
                    "match": ["ccdb", "discord bot"],
                    "links": [
                        {"label": "Status", "obsidian": "Projects/ccdb/status.md"},
                        {"label": "GitHub", "url": "https://github.com/example/ccdb"},
                    ],
                },
                {
                    "match": ["NearJam"],
                    "links": [
                        {"label": "Notes", "obsidian": "Projects/NearJam/status.md"},
                    ],
                },
            ],
        }

    def test_exact_match(self, sample_config: dict[str, Any]) -> None:
        result = match_project("ccdb", sample_config)
        assert result is not None
        assert len(result) == 2

    def test_case_insensitive(self, sample_config: dict[str, Any]) -> None:
        result = match_project("CCDB", sample_config)
        assert result is not None

    def test_substring_match(self, sample_config: dict[str, Any]) -> None:
        result = match_project("ccdb改修の相談", sample_config)
        assert result is not None

    def test_no_match(self, sample_config: dict[str, Any]) -> None:
        result = match_project("unrelated topic", sample_config)
        assert result is None

    def test_second_project_match(self, sample_config: dict[str, Any]) -> None:
        result = match_project("NearJamのバグ修正", sample_config)
        assert result is not None
        assert len(result) == 1

    def test_empty_thread_name(self, sample_config: dict[str, Any]) -> None:
        result = match_project("", sample_config)
        assert result is None

    def test_first_match_wins(self, sample_config: dict[str, Any]) -> None:
        result = match_project("ccdb and NearJam", sample_config)
        assert result is not None
        assert len(result) == 2  # ccdb project has 2 links


# ---------------------------------------------------------------------------
# Pure function tests: build_context_embed
# ---------------------------------------------------------------------------


class TestBuildContextEmbed:
    def test_https_links_are_markdown(self) -> None:
        links = [
            {
                "label": "GitHub",
                "url": "https://github.com/example/ccdb",
                "_resolved": "https://github.com/example/ccdb",
            },
        ]
        embed = build_context_embed(links)
        assert isinstance(embed, discord.Embed)
        assert "GitHub" in (embed.description or "")
        assert "https://github.com/example/ccdb" in (embed.description or "")

    def test_obsidian_links_as_code(self) -> None:
        links = [
            {
                "label": "Status",
                "obsidian": "path.md",
                "_resolved": "obsidian://open?vault=v&file=path.md",
            },
        ]
        embed = build_context_embed(links)
        desc = embed.description or ""
        assert "`obsidian://open" in desc

    def test_mixed_links(self) -> None:
        links = [
            {
                "label": "Status",
                "obsidian": "path.md",
                "_resolved": "obsidian://open?vault=v&file=path.md",
            },
            {
                "label": "GitHub",
                "url": "https://github.com/test",
                "_resolved": "https://github.com/test",
            },
        ]
        embed = build_context_embed(links)
        desc = embed.description or ""
        assert "Status" in desc
        assert "GitHub" in desc

    def test_embed_title(self) -> None:
        links = [
            {"label": "Test", "url": "https://example.com", "_resolved": "https://example.com"},
        ]
        embed = build_context_embed(links)
        assert embed.title is not None


# ---------------------------------------------------------------------------
# Cog integration tests
# ---------------------------------------------------------------------------


class TestContextLinksCog:
    @pytest.fixture()
    def config_file(self, tmp_path: Path) -> str:
        config_data = {
            "obsidian_vault": "obsidian",
            "projects": [
                {
                    "match": ["ccdb", "discord bot"],
                    "links": [
                        {"label": "Status", "obsidian": "Projects/ccdb/status.md"},
                        {"label": "GitHub", "url": "https://github.com/example/ccdb"},
                    ],
                },
            ],
        }
        config_file = tmp_path / "context_links.json"
        config_file.write_text(json.dumps(config_data))
        return str(config_file)

    @pytest.fixture()
    def bot(self) -> MagicMock:
        return MagicMock(spec=discord.ext.commands.Bot)

    def test_init_with_valid_config(self, bot: MagicMock, config_file: str) -> None:
        cog = ContextLinksCog(bot, config_path=config_file)
        assert cog._config is not None

    def test_init_with_no_config(self, bot: MagicMock) -> None:
        cog = ContextLinksCog(bot, config_path="/nonexistent/path.json")
        assert cog._config is None

    def test_init_with_channel_ids(self, bot: MagicMock, config_file: str) -> None:
        cog = ContextLinksCog(bot, config_path=config_file, channel_ids={123, 456})
        assert cog._channel_ids == {123, 456}

    @pytest.mark.asyncio()
    async def test_on_thread_create_matching(self, bot: MagicMock, config_file: str) -> None:
        cog = ContextLinksCog(bot, config_path=config_file, channel_ids={100})
        thread = AsyncMock(spec=discord.Thread)
        thread.name = "ccdbのバグ修正"
        thread.parent_id = 100
        thread.send = AsyncMock()

        await cog.on_thread_create(thread)

        thread.send.assert_called_once()
        call_kwargs = thread.send.call_args
        assert "embed" in call_kwargs.kwargs

    @pytest.mark.asyncio()
    async def test_on_thread_create_no_match(self, bot: MagicMock, config_file: str) -> None:
        cog = ContextLinksCog(bot, config_path=config_file, channel_ids={100})
        thread = AsyncMock(spec=discord.Thread)
        thread.name = "unrelated topic"
        thread.parent_id = 100
        thread.send = AsyncMock()

        await cog.on_thread_create(thread)

        thread.send.assert_not_called()

    @pytest.mark.asyncio()
    async def test_on_thread_create_wrong_channel(self, bot: MagicMock, config_file: str) -> None:
        cog = ContextLinksCog(bot, config_path=config_file, channel_ids={100})
        thread = AsyncMock(spec=discord.Thread)
        thread.name = "ccdb"
        thread.parent_id = 999
        thread.send = AsyncMock()

        await cog.on_thread_create(thread)

        thread.send.assert_not_called()

    @pytest.mark.asyncio()
    async def test_on_thread_create_no_channel_filter(
        self, bot: MagicMock, config_file: str
    ) -> None:
        cog = ContextLinksCog(bot, config_path=config_file, channel_ids=None)
        thread = AsyncMock(spec=discord.Thread)
        thread.name = "ccdb"
        thread.parent_id = 999
        thread.send = AsyncMock()

        await cog.on_thread_create(thread)

        thread.send.assert_called_once()

    @pytest.mark.asyncio()
    async def test_on_thread_create_no_config(self, bot: MagicMock) -> None:
        cog = ContextLinksCog(bot, config_path="/nonexistent.json")
        thread = AsyncMock(spec=discord.Thread)
        thread.name = "ccdb"
        thread.parent_id = 100
        thread.send = AsyncMock()

        await cog.on_thread_create(thread)

        thread.send.assert_not_called()

    @pytest.mark.asyncio()
    async def test_discord_error_suppressed(self, bot: MagicMock, config_file: str) -> None:
        cog = ContextLinksCog(bot, config_path=config_file, channel_ids=None)
        thread = AsyncMock(spec=discord.Thread)
        thread.name = "ccdb"
        thread.parent_id = 100
        thread.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "error"))

        await cog.on_thread_create(thread)
