"""Architecture tests — enforce structural rules that prevent code duplication.

These tests catch violations at CI time, not at code review time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COGS_DIR = Path(__file__).parent.parent / "claude_discord" / "cogs"
RUN_HELPER = COGS_DIR / "_run_helper.py"


class TestNoDirectRunnerRunInCogs:
    """Cog files must NOT call runner.run() directly.

    All Claude CLI execution must go through _run_helper.run_claude_with_config()
    (or the backward-compat shim run_claude_in_thread()).
    Direct runner.run() calls bypass the shared rich experience (streaming text,
    tool result embeds, thinking, intermediate text posting) and create
    maintenance burden when the experience is updated.

    If you need Claude CLI execution in a Cog, use:
        from ._run_helper import run_claude_with_config
        from .run_config import RunConfig
        await run_claude_with_config(RunConfig(thread=..., runner=..., prompt=...))

    The ONLY file allowed to call runner.run() directly is _run_helper.py itself.
    """

    # Pattern matches a bare variable named "runner" calling .run() directly.
    # Excludes attribute access patterns like config.runner.run() or self.runner.run()
    # which are allowed (they go through _run_helper orchestration).
    # Only matches: runner.run( at the start of an identifier boundary.
    _RUNNER_RUN_PATTERN = re.compile(r"(?<![.\w])runner\.run\s*\(")

    def _get_cog_files(self) -> list[Path]:
        """Return all .py files in cogs/ except the core execution modules."""
        excluded = {"_run_helper.py", "run_config.py", "__init__.py"}
        return [f for f in COGS_DIR.glob("*.py") if f.name not in excluded]

    def test_no_direct_runner_run_in_cogs(self) -> None:
        """No Cog file should call runner.run() directly."""
        violations = []
        for cog_file in self._get_cog_files():
            content = cog_file.read_text()
            matches = list(self._RUNNER_RUN_PATTERN.finditer(content))
            if matches:
                lines = content.splitlines()
                for match in matches:
                    # Find line number
                    line_no = content[: match.start()].count("\n") + 1
                    violations.append(f"  {cog_file.name}:{line_no}: {lines[line_no - 1].strip()}")

        if violations:
            msg = (
                "Direct runner.run() calls found in Cog files.\n"
                "Use run_claude_with_config() from _run_helper instead:\n" + "\n".join(violations)
            )
            pytest.fail(msg)

    def test_run_helper_exists(self) -> None:
        """_run_helper.py must exist — it's the single source of truth."""
        assert RUN_HELPER.exists(), "_run_helper.py is missing from cogs/"

    def test_run_helper_exports_run_claude_with_config(self) -> None:
        """_run_helper must export the primary run_claude_with_config function."""
        content = RUN_HELPER.read_text()
        assert "async def run_claude_with_config" in content

    def test_run_helper_exports_run_claude_in_thread(self) -> None:
        """_run_helper must also export the backward-compat shim."""
        content = RUN_HELPER.read_text()
        assert "async def run_claude_in_thread" in content
