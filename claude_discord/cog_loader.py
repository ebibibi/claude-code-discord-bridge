"""Dynamic loader for custom Cogs from external directories.

Consumers place Cog files in a directory and point ccdb at it via
``CUSTOM_COGS_DIR`` env or ``--cogs-dir`` CLI flag.  Each file must
expose an ``async def setup(bot, runner, components)`` entry point.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext.commands import Bot

    from claude_code_core.backend import SessionBackend

    from .setup import BridgeComponents

logger = logging.getLogger(__name__)


async def load_custom_cogs(
    cogs_dir: Path,
    bot: Bot,
    runner: SessionBackend | None,
    components: BridgeComponents,
) -> int:
    """Load custom Cog files from *cogs_dir*.

    Each ``.py`` file (excluding ``_``-prefixed files) must define::

        async def setup(bot, runner, components):
            await bot.add_cog(MyCog(bot, ...))

    A single Cog's failure is logged and skipped — it never prevents
    other Cogs from loading.

    Args:
        cogs_dir: Directory containing ``.py`` Cog files.
        bot: Discord bot instance.
        runner: ClaudeRunner (may be ``None`` if Claude chat is disabled).
        components: BridgeComponents from ``setup_bridge()``.

    Returns:
        Number of successfully loaded Cog files.
    """
    if not cogs_dir.is_dir():
        logger.warning("Custom cogs directory does not exist: %s", cogs_dir)
        return 0

    files = sorted(
        p for p in cogs_dir.iterdir() if p.suffix == ".py" and not p.name.startswith("_")
    )

    if not files:
        logger.info("No custom cog files found in %s", cogs_dir)
        return 0

    loaded = 0
    for path in files:
        module_name = f"_ccdb_custom_cog_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                logger.error("Failed to create module spec for %s", path)
                continue

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            setup_fn = getattr(module, "setup", None)
            if setup_fn is None:
                logger.warning("No setup() function in %s — skipped", path.name)
                continue

            await setup_fn(bot, runner, components)
            loaded += 1
            logger.info("Loaded custom cog: %s", path.name)

        except Exception:
            logger.exception("Failed to load custom cog: %s", path.name)
            # Clean up partial module registration
            sys.modules.pop(module_name, None)

    logger.info("Custom cogs loaded: %d/%d from %s", loaded, len(files), cogs_dir)
    return loaded
