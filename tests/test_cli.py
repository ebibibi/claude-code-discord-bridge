"""Tests for the ccdb CLI wizard.

TDD: These tests were written BEFORE the implementation.
They define the expected behavior of the setup wizard.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discord_response(status: int, data: object) -> MagicMock:
    """Create a mock aiohttp response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(get_response: MagicMock) -> MagicMock:
    """Create a mock aiohttp.ClientSession."""
    session = MagicMock()
    session.get = MagicMock(return_value=get_response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------


class TestValidateToken:
    """Tests for validate_token()."""

    @pytest.mark.asyncio
    async def test_returns_bot_name_on_success(self) -> None:
        from claude_discord.cli import validate_token

        resp = _make_discord_response(200, {"username": "MyBot", "discriminator": "1234"})
        session = _make_session(resp)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await validate_token("Bot valid.token.here")
        assert result == "MyBot#1234"

    @pytest.mark.asyncio
    async def test_returns_none_on_401(self) -> None:
        from claude_discord.cli import validate_token

        resp = _make_discord_response(401, {"message": "401: Unauthorized"})
        session = _make_session(resp)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await validate_token("Bot bad.token")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self) -> None:
        import aiohttp

        from claude_discord.cli import validate_token

        session = MagicMock()
        session.get = MagicMock(side_effect=aiohttp.ClientError())
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await validate_token("Bot valid.token.here")
        assert result is None


# ---------------------------------------------------------------------------
# fetch_channels
# ---------------------------------------------------------------------------


class TestFetchChannels:
    """Tests for fetch_channels() — returns list of (channel_id, name, guild_name)."""

    @pytest.mark.asyncio
    async def test_returns_text_channels(self) -> None:
        from claude_discord.cli import fetch_channels

        channels_resp = _make_discord_response(
            200,
            [
                {"id": "999", "name": "general", "type": 0},  # text channel
                {"id": "888", "name": "voice-chat", "type": 2},  # voice — skip
                {"id": "777", "name": "dev", "type": 0},  # text channel
            ],
        )

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(
            side_effect=[
                _make_discord_response(200, [{"id": "111", "name": "My Server"}]),
                channels_resp,
            ]
        )

        with patch("aiohttp.ClientSession", return_value=session):
            channels = await fetch_channels("Bot valid.token")

        assert len(channels) == 2
        assert channels[0] == ("999", "general", "My Server")
        assert channels[1] == ("777", "dev", "My Server")

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        from claude_discord.cli import fetch_channels

        resp = _make_discord_response(401, {"message": "Unauthorized"})
        session = _make_session(resp)
        with patch("aiohttp.ClientSession", return_value=session):
            channels = await fetch_channels("Bot bad.token")
        assert channels == []


# ---------------------------------------------------------------------------
# write_env
# ---------------------------------------------------------------------------


class TestWriteEnv:
    """Tests for write_env()."""

    def test_writes_required_vars(self, tmp_path: Path) -> None:
        from claude_discord.cli import write_env

        env_file = tmp_path / ".env"
        write_env(
            path=env_file,
            token="mytoken",
            channel_id="123",
            owner_id="456",
            working_dir="/home/user/project",
            model="sonnet",
        )
        content = env_file.read_text()
        assert "DISCORD_BOT_TOKEN=mytoken" in content
        assert "DISCORD_CHANNEL_ID=123" in content
        assert "DISCORD_OWNER_ID=456" in content
        assert "CLAUDE_WORKING_DIR=/home/user/project" in content
        assert "CLAUDE_MODEL=sonnet" in content

    def test_skips_empty_owner_id(self, tmp_path: Path) -> None:
        from claude_discord.cli import write_env

        env_file = tmp_path / ".env"
        write_env(
            path=env_file,
            token="mytoken",
            channel_id="123",
            owner_id="",
            working_dir="",
            model="sonnet",
        )
        content = env_file.read_text()
        # owner_id line should still exist but be empty
        assert "DISCORD_OWNER_ID=" in content

    def test_does_not_overwrite_without_flag(self, tmp_path: Path) -> None:
        from claude_discord.cli import write_env

        env_file = tmp_path / ".env"
        env_file.write_text("DISCORD_BOT_TOKEN=original\n")
        with pytest.raises(FileExistsError):
            write_env(
                path=env_file,
                token="new",
                channel_id="123",
                owner_id="",
                working_dir="",
                model="sonnet",
            )
        assert "original" in env_file.read_text()

    def test_overwrites_with_flag(self, tmp_path: Path) -> None:
        from claude_discord.cli import write_env

        env_file = tmp_path / ".env"
        env_file.write_text("DISCORD_BOT_TOKEN=original\n")
        write_env(
            path=env_file,
            token="new",
            channel_id="123",
            owner_id="",
            working_dir="",
            model="sonnet",
            overwrite=True,
        )
        assert "new" in env_file.read_text()
        assert "original" not in env_file.read_text()


# ---------------------------------------------------------------------------
# check_claude_cli
# ---------------------------------------------------------------------------


class TestCheckClaudeCli:
    """Tests for check_claude_cli()."""

    def test_returns_true_when_installed(self) -> None:
        from claude_discord.cli import check_claude_cli

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="claude 1.0.0")
            assert check_claude_cli() is True

    def test_returns_false_when_not_found(self) -> None:

        from claude_discord.cli import check_claude_cli

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert check_claude_cli() is False


# ---------------------------------------------------------------------------
# main() — subcommand routing
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the top-level main() entry point."""

    def test_no_args_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        from claude_discord.cli import main

        with patch("sys.argv", ["ccdb"]), pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "setup" in captured.out or "setup" in captured.err

    def test_unknown_command_exits_nonzero(self) -> None:
        from claude_discord.cli import main

        with patch("sys.argv", ["ccdb", "nonexistent"]), pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code != 0

    def test_start_without_env_exits_with_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_discord.cli import cmd_start

        env_path = tmp_path / ".env"
        with pytest.raises(SystemExit) as exc_info:
            cmd_start(env_path=env_path)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "setup" in captured.out or "setup" in captured.err
