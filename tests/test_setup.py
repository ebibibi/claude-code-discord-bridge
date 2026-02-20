"""Tests for setup_bridge() auto-discovery function."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.setup import BridgeComponents, setup_bridge


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.loop = MagicMock()
    bot.add_cog = AsyncMock()
    return bot


def _make_runner() -> MagicMock:
    runner = MagicMock()
    runner.clone.return_value = runner
    return runner


@pytest.mark.asyncio
async def test_setup_bridge_registers_core_cogs(tmp_path: object) -> None:
    """setup_bridge should register ClaudeChatCog, SessionManageCog, SkillCommandCog."""
    bot = _make_bot()
    runner = _make_runner()

    result = await setup_bridge(
        bot,
        runner,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        claude_channel_id=12345,
        enable_scheduler=False,
    )

    cog_names = [call.args[0].__class__.__name__ for call in bot.add_cog.call_args_list]
    assert "ClaudeChatCog" in cog_names
    assert "SessionManageCog" in cog_names
    assert "SkillCommandCog" in cog_names
    assert isinstance(result, BridgeComponents)


@pytest.mark.asyncio
async def test_setup_bridge_registers_scheduler_when_enabled(tmp_path: object) -> None:
    """setup_bridge should register SchedulerCog when enable_scheduler=True."""
    bot = _make_bot()
    runner = _make_runner()

    result = await setup_bridge(
        bot,
        runner,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        enable_scheduler=True,
        task_db_path=str(tmp_path / "tasks.db"),  # type: ignore[operator]
    )

    cog_names = [call.args[0].__class__.__name__ for call in bot.add_cog.call_args_list]
    assert "SchedulerCog" in cog_names
    assert result.task_repo is not None


@pytest.mark.asyncio
async def test_setup_bridge_skips_scheduler_when_disabled(tmp_path: object) -> None:
    """setup_bridge should NOT register SchedulerCog when enable_scheduler=False."""
    bot = _make_bot()
    runner = _make_runner()

    result = await setup_bridge(
        bot,
        runner,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        enable_scheduler=False,
    )

    cog_names = [call.args[0].__class__.__name__ for call in bot.add_cog.call_args_list]
    assert "SchedulerCog" not in cog_names
    assert result.task_repo is None


@pytest.mark.asyncio
async def test_setup_bridge_returns_components(tmp_path: object) -> None:
    """setup_bridge should return BridgeComponents with session_repo."""
    bot = _make_bot()
    runner = _make_runner()

    result = await setup_bridge(
        bot,
        runner,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        enable_scheduler=False,
    )

    assert isinstance(result, BridgeComponents)
    assert result.session_repo is not None
    assert result.session_repo.db_path == str(tmp_path / "sessions.db")  # type: ignore[operator]


@pytest.mark.asyncio
async def test_setup_bridge_skips_skill_cog_without_channel_id(tmp_path: object) -> None:
    """setup_bridge should skip SkillCommandCog when claude_channel_id is None."""
    bot = _make_bot()
    runner = _make_runner()

    await setup_bridge(
        bot,
        runner,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        claude_channel_id=None,
        enable_scheduler=False,
    )

    cog_names = [call.args[0].__class__.__name__ for call in bot.add_cog.call_args_list]
    assert "SkillCommandCog" not in cog_names
