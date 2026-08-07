"""Tests for claude_discord.cog_loader.load_custom_cogs."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.cog_loader import load_custom_cogs


@pytest.fixture
def cogs_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for custom Cog files."""
    d = tmp_path / "cogs"
    d.mkdir()
    return d


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.add_cog = AsyncMock()
    return bot


@pytest.fixture
def mock_components() -> MagicMock:
    return MagicMock()


async def test_load_empty_dir(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """Empty directory should load 0 cogs."""
    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 0


async def test_load_nonexistent_dir(
    mock_bot: MagicMock, mock_components: MagicMock, tmp_path: Path
) -> None:
    """Non-existent directory should return 0 without error."""
    result = await load_custom_cogs(tmp_path / "nope", mock_bot, None, mock_components)
    assert result == 0


async def test_load_valid_cog(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """A valid Cog file with setup() should be loaded."""
    cog_file = cogs_dir / "hello.py"
    cog_file.write_text(
        textwrap.dedent("""\
        async def setup(bot, runner, components):
            bot._test_hello_loaded = True
    """)
    )

    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 1
    assert mock_bot._test_hello_loaded is True


async def test_skip_underscore_prefix(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """Files starting with _ should be skipped."""
    (cogs_dir / "_helper.py").write_text(
        "async def setup(bot, runner, components): pass", encoding="utf-8"
    )
    (cogs_dir / "good.py").write_text(
        "async def setup(bot, runner, components): pass", encoding="utf-8"
    )

    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 1  # only good.py


async def test_skip_non_py_files(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """Non-.py files should be ignored."""
    (cogs_dir / "readme.txt").write_text("not a cog", encoding="utf-8")
    (cogs_dir / "config.json").write_text("{}", encoding="utf-8")

    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 0


async def test_skip_no_setup_function(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """A .py file without setup() should be skipped with a warning."""
    (cogs_dir / "no_setup.py").write_text("x = 42", encoding="utf-8")

    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 0


async def test_one_failure_does_not_block_others(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """A broken Cog should not prevent other Cogs from loading."""
    # aaa.py loads first (sorted order) — broken
    (cogs_dir / "aaa_broken.py").write_text(
        textwrap.dedent("""\
        async def setup(bot, runner, components):
            raise RuntimeError("intentional failure")
    """)
    )
    # bbb.py loads second — good
    (cogs_dir / "bbb_good.py").write_text(
        textwrap.dedent("""\
        async def setup(bot, runner, components):
            bot._test_bbb_loaded = True
    """)
    )

    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 1
    assert mock_bot._test_bbb_loaded is True


async def test_deterministic_load_order(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """Cogs should be loaded in sorted filename order."""
    load_order: list[str] = []

    for name in ["charlie.py", "alpha.py", "bravo.py"]:
        (cogs_dir / name).write_text(
            textwrap.dedent(f"""\
            async def setup(bot, runner, components):
                bot._load_order.append("{name}")
        """)
        )

    mock_bot._load_order = load_order
    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 3
    assert load_order == ["alpha.py", "bravo.py", "charlie.py"]


async def test_runner_and_components_passed(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """setup() should receive bot, runner, and components."""
    (cogs_dir / "check_args.py").write_text(
        textwrap.dedent("""\
        async def setup(bot, runner, components):
            bot._test_runner = runner
            bot._test_components = components
    """)
    )

    mock_runner = MagicMock()
    result = await load_custom_cogs(cogs_dir, mock_bot, mock_runner, mock_components)
    assert result == 1
    assert mock_bot._test_runner is mock_runner
    assert mock_bot._test_components is mock_components


async def test_syntax_error_in_cog(
    cogs_dir: Path, mock_bot: MagicMock, mock_components: MagicMock
) -> None:
    """A file with syntax errors should be skipped gracefully."""
    (cogs_dir / "bad_syntax.py").write_text(
        "def setup(bot, runner, components) oops", encoding="utf-8"
    )

    result = await load_custom_cogs(cogs_dir, mock_bot, None, mock_components)
    assert result == 0
