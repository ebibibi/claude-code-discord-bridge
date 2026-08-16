"""Source that ships in a public repository must not name a real person.

``examples/ebibot`` is a real instance's configuration, so it is the place where
personal detail leaks in: a docstring explaining *why* a Cog exists is the most
natural thing in the world to write, and the natural way to write it is to name
the person whose workflow it serves. This test makes that a build failure rather
than something a reviewer has to notice.

The check is deliberately narrow — names, not topics. A broad "no Japanese", or
a list of tools someone might use, produces false positives that get suppressed,
and a suppressed guard is not a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).parent.parent

_SCANNED_ROOTS = (
    _REPO / "claude_discord",
    _REPO / "claude_code_core",
    _REPO / "claude_teams",
    _REPO / "examples",
)

# Real-person identifiers. The GitHub account name is excluded on purpose: it is
# the repository owner and appears legitimately in clone URLs.
_PERSONAL = re.compile(r"胡田|ebisuda", re.IGNORECASE)


def test_no_personal_identifiers_in_shipped_source() -> None:
    violations = []
    for root in _SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _PERSONAL.search(line):
                    violations.append(f"  {path.relative_to(_REPO)}:{lineno}: {line.strip()[:80]}")

    assert not violations, (
        "This repository is public. Source must not name a real person — put the "
        "personal half in an external file the instance points at (see "
        "THREAD_COMPLETION_PROMPT_FILE for the pattern):\n" + "\n".join(violations)
    )
