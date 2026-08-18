"""Every thread we create must ask Discord for the longest visibility window.

A thread that Discord auto-archives drops out of the channel's thread list. The
window is fixed at creation time, so a call site that forgets the keyword silently
inherits discord.py's default and the conversation disappears from the sidebar
while the user still considers it open. This is an architecture test: it fails
when a *new* ``create_thread`` call site forgets, which is the way this
regresses.
"""

from __future__ import annotations

import ast
from pathlib import Path

from claude_discord.thread_policy import THREAD_AUTO_ARCHIVE_MINUTES

_REPO = Path(__file__).parent.parent
PACKAGE_DIR = _REPO / "claude_discord"
# EbiBot's Cogs create threads too, and a thread that vanishes is just as wrong
# there — the rule is about Discord's behaviour, not about which package we are in.
_SCANNED_ROOTS = (PACKAGE_DIR, _REPO / "examples" / "ebibot" / "cogs")

# The only values Discord accepts, in minutes.
_ALLOWED_WINDOWS = (60, 1440, 4320, 10080)


def _create_thread_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_thread"
    ]


class TestThreadAutoArchiveWindow:
    def test_constant_is_discords_maximum(self) -> None:
        assert THREAD_AUTO_ARCHIVE_MINUTES in _ALLOWED_WINDOWS
        assert max(_ALLOWED_WINDOWS) == THREAD_AUTO_ARCHIVE_MINUTES

    def test_every_call_site_passes_the_constant(self) -> None:
        violations = []
        for path in sorted(p for root in _SCANNED_ROOTS for p in root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _create_thread_calls(tree):
                kwarg = next((k for k in call.keywords if k.arg == "auto_archive_duration"), None)
                rel = path.relative_to(_REPO)
                if kwarg is None:
                    violations.append(f"  {rel}:{call.lineno}: no auto_archive_duration")
                elif not (
                    isinstance(kwarg.value, ast.Name)
                    and kwarg.value.id == "THREAD_AUTO_ARCHIVE_MINUTES"
                ):
                    violations.append(
                        f"  {rel}:{call.lineno}: auto_archive_duration is not the shared constant"
                    )

        assert not violations, (
            "create_thread() call sites must pass "
            "auto_archive_duration=THREAD_AUTO_ARCHIVE_MINUTES "
            "(from claude_discord.thread_policy), or the thread vanishes from the "
            "channel's thread list while the user still considers it open:\n"
            + "\n".join(violations)
        )

    def test_the_scan_actually_finds_call_sites(self) -> None:
        """Guard against the scan silently matching nothing and passing forever."""
        found = sum(
            len(_create_thread_calls(ast.parse(p.read_text(encoding="utf-8"))))
            for root in _SCANNED_ROOTS
            for p in root.rglob("*.py")
        )
        assert found >= 8, f"expected the package to still create threads, found {found}"
