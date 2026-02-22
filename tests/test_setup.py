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


# ---------------------------------------------------------------------------
# apply_to_api_server()
# ---------------------------------------------------------------------------


def _make_api_server() -> MagicMock:
    server = MagicMock()
    server.task_repo = None
    server.lounge_repo = None
    server.port = 8099
    return server


def test_apply_to_api_server_wires_task_and_lounge_repos(tmp_path: object) -> None:
    """apply_to_api_server should set task_repo and lounge_repo on the ApiServer."""
    from claude_discord.database.lounge_repo import LoungeRepository
    from claude_discord.database.repository import SessionRepository
    from claude_discord.database.task_repo import TaskRepository

    session_repo = MagicMock(spec=SessionRepository)
    task_repo = MagicMock(spec=TaskRepository)
    lounge_repo = MagicMock(spec=LoungeRepository)

    components = BridgeComponents(
        session_repo=session_repo,
        task_repo=task_repo,
        lounge_repo=lounge_repo,
    )
    api_server = _make_api_server()

    components.apply_to_api_server(api_server)

    assert api_server.task_repo is task_repo
    assert api_server.lounge_repo is lounge_repo


def test_apply_to_api_server_skips_none_repos() -> None:
    """apply_to_api_server should not overwrite existing repos with None."""
    from claude_discord.database.repository import SessionRepository

    session_repo = MagicMock(spec=SessionRepository)
    components = BridgeComponents(
        session_repo=session_repo,
        task_repo=None,
        lounge_repo=None,
    )
    api_server = _make_api_server()
    existing_task_repo = MagicMock()
    api_server.task_repo = existing_task_repo

    components.apply_to_api_server(api_server)

    # None repos must not overwrite existing values
    assert api_server.task_repo is existing_task_repo


def test_apply_to_api_server_is_idempotent() -> None:
    """apply_to_api_server called twice should leave the same repo references."""
    from claude_discord.database.lounge_repo import LoungeRepository
    from claude_discord.database.repository import SessionRepository
    from claude_discord.database.task_repo import TaskRepository

    session_repo = MagicMock(spec=SessionRepository)
    task_repo = MagicMock(spec=TaskRepository)
    lounge_repo = MagicMock(spec=LoungeRepository)

    components = BridgeComponents(
        session_repo=session_repo,
        task_repo=task_repo,
        lounge_repo=lounge_repo,
    )
    api_server = _make_api_server()

    components.apply_to_api_server(api_server)
    components.apply_to_api_server(api_server)

    assert api_server.task_repo is task_repo
    assert api_server.lounge_repo is lounge_repo


@pytest.mark.asyncio
async def test_setup_bridge_auto_wires_api_server(tmp_path: object) -> None:
    """setup_bridge(api_server=...) should auto-wire repos and set runner.api_port."""
    bot = _make_bot()
    runner = _make_runner()
    runner.api_port = None  # Not set yet
    api_server = _make_api_server()

    result = await setup_bridge(
        bot,
        runner,
        api_server=api_server,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        enable_scheduler=True,
        task_db_path=str(tmp_path / "tasks.db"),  # type: ignore[operator]
    )

    # Repos should be wired automatically
    assert api_server.task_repo is result.task_repo
    assert api_server.lounge_repo is result.lounge_repo
    # runner.api_port should be set from api_server.port
    assert runner.api_port == api_server.port


@pytest.mark.asyncio
async def test_setup_bridge_preserves_existing_runner_api_port(tmp_path: object) -> None:
    """setup_bridge should not overwrite runner.api_port if already set."""
    bot = _make_bot()
    runner = _make_runner()
    runner.api_port = 9999  # Already set
    api_server = _make_api_server()
    api_server.port = 8099

    await setup_bridge(
        bot,
        runner,
        api_server=api_server,
        session_db_path=str(tmp_path / "sessions.db"),  # type: ignore[operator]
        enable_scheduler=False,
    )

    # Should NOT overwrite the existing value
    assert runner.api_port == 9999
