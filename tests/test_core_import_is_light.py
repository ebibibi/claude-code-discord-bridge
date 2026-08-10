"""Importing a protocol must not require a database driver.

`claude_code_core.frontend` is protocols and value objects. It had no storage
in it and could not be imported without `aiosqlite`, because the package's
`__init__` eagerly imported the repositories. That is not a tidiness point: the
Teams relay receiver runs on a public machine built with nothing but an HTTP
server and a JWT library, and it crashed on startup with `ModuleNotFoundError:
aiosqlite` — a dependency it has no reason to carry.

Checked in a subprocess because import side effects cannot be undone in-process
once another test has already imported the world.
"""

from __future__ import annotations

import subprocess
import sys


def run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


class TestTheProtocolImportsAlone:
    def test_frontend_does_not_pull_in_the_database_layer(self) -> None:
        result = run(
            "import sys, claude_code_core.frontend;"
            "assert 'aiosqlite' not in sys.modules, 'frontend dragged in aiosqlite';"
            "assert 'claude_code_core.session_repo' not in sys.modules"
        )
        assert result.returncode == 0, result.stderr

    def test_the_teams_package_does_not_either(self) -> None:
        # This is the one that actually broke a deployment.
        result = run(
            "import sys, claude_teams;"
            "assert 'aiosqlite' not in sys.modules, 'claude_teams dragged in aiosqlite';"
            "assert 'discord' not in sys.modules, 'claude_teams dragged in discord.py'"
        )
        assert result.returncode == 0, result.stderr


class TestTheLazyMembersStillWork:
    def test_the_repositories_are_still_importable_from_the_package(self) -> None:
        # PEP 562 must not change the public API, only when it resolves.
        result = run(
            "from claude_code_core import SessionRepository, LoungeRepository, init_db;"
            "assert SessionRepository and LoungeRepository and init_db"
        )
        assert result.returncode == 0, result.stderr

    def test_an_unknown_attribute_still_raises_attribute_error(self) -> None:
        result = run(
            "import claude_code_core\n"
            "try:\n"
            "    claude_code_core.NoSuchThing\n"
            "except AttributeError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('expected AttributeError')\n"
        )
        assert result.returncode == 0, result.stderr
