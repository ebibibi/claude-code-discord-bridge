"""Tests for claude_discord.main.load_config()."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestLoadConfig:
    """Tests for load_config() environment parsing.

    load_dotenv() is patched out in all tests to prevent .env file
    from polluting test results.
    """

    def test_missing_token_exits(self) -> None:
        """Missing DISCORD_BOT_TOKEN causes sys.exit(1)."""
        from claude_discord.main import load_config

        with (
            patch("claude_discord.main.load_dotenv"),
            patch.dict(
                "os.environ",
                {"DISCORD_CHANNEL_ID": "123"},
                clear=True,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            load_config()
        assert exc_info.value.code == 1

    def test_missing_channel_id_exits(self) -> None:
        """Missing DISCORD_CHANNEL_ID causes sys.exit(1)."""
        from claude_discord.main import load_config

        with (
            patch("claude_discord.main.load_dotenv"),
            patch.dict(
                "os.environ",
                {"DISCORD_BOT_TOKEN": "fake-token"},
                clear=True,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            load_config()
        assert exc_info.value.code == 1

    def test_valid_config_returns_dict(self) -> None:
        """Valid token + channel returns a dict with all keys."""
        from claude_discord.main import load_config

        with (
            patch("claude_discord.main.load_dotenv"),
            patch.dict(
                "os.environ",
                {
                    "DISCORD_BOT_TOKEN": "fake-token",
                    "DISCORD_CHANNEL_ID": "123456",
                },
                clear=True,
            ),
        ):
            config = load_config()

        assert config["token"] == "fake-token"
        assert config["channel_id"] == "123456"
        assert config["claude_command"] == "claude"
        assert config["claude_model"] == "sonnet"
        assert config["claude_permission_mode"] == "acceptEdits"
        assert config["max_concurrent"] == "3"
        assert config["timeout"] == "300"
        assert config["custom_cogs_dir"] == ""

    def test_all_optional_env_vars(self) -> None:
        """Optional env vars are correctly read."""
        from claude_discord.main import load_config

        with (
            patch("claude_discord.main.load_dotenv"),
            patch.dict(
                "os.environ",
                {
                    "DISCORD_BOT_TOKEN": "tok",
                    "DISCORD_CHANNEL_ID": "111",
                    "CLAUDE_COMMAND": "/usr/bin/claude",
                    "CLAUDE_MODEL": "opus",
                    "CLAUDE_PERMISSION_MODE": "bypassPermissions",
                    "CLAUDE_WORKING_DIR": "/home/test",
                    "MAX_CONCURRENT_SESSIONS": "5",
                    "SESSION_TIMEOUT_SECONDS": "600",
                    "DISCORD_OWNER_ID": "999",
                    "COORDINATION_CHANNEL_ID": "888",
                    "CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS": "true",
                    "CLAUDE_CHANNEL_IDS": "111,222,333",
                    "API_HOST": "0.0.0.0",
                    "API_PORT": "9000",
                    "CLAUDE_ALLOWED_TOOLS": "Read,Write",
                    "CUSTOM_COGS_DIR": "/my/cogs",
                },
                clear=True,
            ),
        ):
            config = load_config()

        assert config["claude_command"] == "/usr/bin/claude"
        assert config["claude_model"] == "opus"
        assert config["claude_working_dir"] == "/home/test"
        assert config["max_concurrent"] == "5"
        assert config["owner_id"] == "999"
        assert config["coordination_channel_id"] == "888"
        assert config["claude_channel_ids"] == "111,222,333"
        assert config["api_host"] == "0.0.0.0"
        assert config["api_port"] == "9000"
        assert config["allowed_tools"] == "Read,Write"
        assert config["custom_cogs_dir"] == "/my/cogs"

    def test_dangerously_skip_permissions_is_string(self) -> None:
        """dangerously_skip_permissions is returned as string, not bool."""
        from claude_discord.main import load_config

        with (
            patch("claude_discord.main.load_dotenv"),
            patch.dict(
                "os.environ",
                {
                    "DISCORD_BOT_TOKEN": "tok",
                    "DISCORD_CHANNEL_ID": "111",
                    "CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS": "true",
                },
                clear=True,
            ),
        ):
            config = load_config()

        # Must be str to satisfy dict[str, str] return type
        assert isinstance(config["dangerously_skip_permissions"], str)


class TestExampleCogImports:
    """Verify that example cog files can be imported and have setup()."""

    @pytest.mark.parametrize(
        "cog_name",
        ["auto_upgrade", "docs_sync", "reminder", "watchdog"],
    )
    def test_example_cog_has_setup(self, cog_name: str) -> None:
        """Each example cog file exposes an async setup() function."""
        import importlib.util
        import sys
        from pathlib import Path

        cog_path = Path(__file__).parent.parent / "examples" / "ebibot" / "cogs" / f"{cog_name}.py"
        assert cog_path.exists(), f"{cog_path} does not exist"

        module_name = f"_test_example_{cog_name}"
        spec = importlib.util.spec_from_file_location(module_name, cog_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        setup_fn = getattr(module, "setup", None)
        assert setup_fn is not None, f"{cog_name}.py missing setup() function"
        assert callable(setup_fn)

        del sys.modules[module_name]
