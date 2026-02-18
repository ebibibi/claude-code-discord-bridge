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

    All Claude CLI execution must go through _run_helper.run_claude_in_thread().
    Direct runner.run() calls bypass the shared rich experience (streaming text,
    tool result embeds, thinking, intermediate text posting) and create
    maintenance burden when the experience is updated.

    If you need Claude CLI execution in a Cog, use:
        from ._run_helper import run_claude_in_thread
        await run_claude_in_thread(thread, runner, repo, prompt, session_id)

    The ONLY file allowed to call runner.run() directly is _run_helper.py itself.
    """

    # Pattern matches: runner.run(, self.runner.run(, any_var.run(prompt
    # but NOT: run_claude_in_thread (which is the correct usage)
    _RUNNER_RUN_PATTERN = re.compile(r"\brunner\.run\s*\(")

    def _get_cog_files(self) -> list[Path]:
        """Return all .py files in cogs/ except _run_helper.py."""
        return [
            f
            for f in COGS_DIR.glob("*.py")
            if f.name not in ("_run_helper.py", "__init__.py")
        ]

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
                    line_no = content[:match.start()].count("\n") + 1
                    violations.append(f"  {cog_file.name}:{line_no}: {lines[line_no - 1].strip()}")

        if violations:
            msg = (
                "Direct runner.run() calls found in Cog files.\n"
                "Use run_claude_in_thread() from _run_helper instead:\n"
                + "\n".join(violations)
            )
            pytest.fail(msg)

    def test_run_helper_exists(self) -> None:
        """_run_helper.py must exist — it's the single source of truth."""
        assert RUN_HELPER.exists(), "_run_helper.py is missing from cogs/"

    def test_run_helper_exports_run_claude_in_thread(self) -> None:
        """_run_helper must export run_claude_in_thread."""
        content = RUN_HELPER.read_text()
        assert "async def run_claude_in_thread" in content
