"""The consumer gate: every shipped example Cog must still load.

``examples/ebibot/cogs/`` is not decoration — it is the reference consumer, and
the very directory a real deployment points ``CUSTOM_COGS_DIR`` at. So it is
also the most faithful check that a change to ccdb's public API has not broken
somebody's Cogs: a renamed constructor argument, a moved import or a dropped
helper all surface here as a failed ``setup()``.

This replaces an earlier CI job that cloned ``ebibibi/discord-bot`` and imported
it. That repository was archived in March 2026, which made the gate both
unfixable (it is read-only, so it can never be updated to track ccdb) and
misleading (it no longer describes how anyone runs the bot). Checking the
in-repo example instead keeps the guarantee, runs on every Python version in
the matrix rather than one, and cannot rot out from under us.

``load_custom_cogs`` deliberately swallows a single Cog's failure so one bad
file never blocks the others — which means the return count is the only signal
that anything went wrong. These tests assert on that count, and also capture
logs so a regression names the Cog that broke.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.cog_loader import load_custom_cogs

EXAMPLE_COGS_DIR = Path(__file__).resolve().parent.parent / "examples" / "ebibot" / "cogs"


def _cog_files() -> list[Path]:
    """The files ``load_custom_cogs`` will actually try to import."""
    return sorted(p for p in EXAMPLE_COGS_DIR.iterdir() if p.suffix == ".py" and p.name[0] != "_")


@pytest.fixture
def bot() -> MagicMock:
    bot = MagicMock()
    bot.add_cog = AsyncMock()
    # docs_sync reads this to decide which channels to listen on.
    bot.channel_id = 123456789
    return bot


@pytest.fixture
def components() -> MagicMock:
    return MagicMock()


@pytest.fixture
def sandbox_cwd(tmp_path: Path):
    """Run with a throwaway working directory.

    ``reminder.py`` opens ``data/bot.db`` relative to the process cwd during
    ``setup()``. Left alone it would create that file in the repository, so the
    test would pass once and then be testing a pre-existing database.
    """
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(original)


class TestExampleCogsLoad:
    def test_directory_is_not_empty(self) -> None:
        """Guard the guard: an empty directory would make every other
        assertion here vacuously true."""
        assert _cog_files(), f"no example Cogs found under {EXAMPLE_COGS_DIR}"

    async def test_every_example_cog_loads(
        self,
        bot: MagicMock,
        components: MagicMock,
        sandbox_cwd: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        expected = _cog_files()

        with caplog.at_level(logging.ERROR, logger="claude_discord.cog_loader"):
            loaded = await load_custom_cogs(EXAMPLE_COGS_DIR, bot, None, components)

        assert loaded == len(expected), (
            f"{len(expected) - loaded} example Cog(s) failed to load. "
            f"Errors: {[r.getMessage() for r in caplog.records]}"
        )

    async def test_loads_without_a_runner(
        self,
        bot: MagicMock,
        components: MagicMock,
        sandbox_cwd: Path,
    ) -> None:
        """``runner`` is None whenever Claude chat is disabled, and the loader
        documents that as supported. A Cog that dereferences it at setup time
        would break those deployments only at startup."""
        loaded = await load_custom_cogs(EXAMPLE_COGS_DIR, bot, None, components)
        assert loaded == len(_cog_files())
