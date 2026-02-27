"""CI guard: _HELP_CATEGORY in claude_chat.py must stay in sync with all slash commands.

How it works
------------
The tests use Python's ``ast`` module to statically parse every cog source file
and collect the names of all ``@app_commands.command(name=...)`` decorators —
without starting a bot process.  The collected names are then compared against
``_HELP_CATEGORY``, the dict that drives the dynamic ``/help`` embed.

Adding a new slash command without updating ``_HELP_CATEGORY`` causes
``test_all_commands_covered`` to fail, surfacing the omission in CI before
anyone notices the help is stale.

Deleting a command while leaving its entry in ``_HELP_CATEGORY`` causes
``test_no_stale_entries`` to fail, keeping the dict tidy.
"""

from __future__ import annotations

import ast
import pathlib

# Directory that contains all cog modules.
_COGS_DIR = pathlib.Path(__file__).parent.parent / "claude_discord" / "cogs"


def _collect_app_command_names() -> set[str]:
    """Return every name= value from @app_commands.command(...) decorators.

    Only matches the exact ``app_commands.command`` form (not prefix-command
    decorators like ``@commands.command``).
    """
    names: set[str] = set()
    for path in sorted(_COGS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # Both sync (FunctionDef) and async (AsyncFunctionDef) defs carry decorators.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                # Must be an attribute access ending in ".command"
                if not (isinstance(func, ast.Attribute) and func.attr == "command"):
                    continue
                # Must be specifically "app_commands.command", not e.g. "commands.command"
                if not (isinstance(func.value, ast.Name) and func.value.id == "app_commands"):
                    continue
                for kw in dec.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        names.add(str(kw.value.value))
    return names


def test_all_commands_covered() -> None:
    """Every @app_commands.command must have an entry in _HELP_CATEGORY.

    Fail message tells the developer exactly which command(s) are missing
    and where to add them.
    """
    from claude_discord.cogs.claude_chat import _HELP_CATEGORY

    registered = _collect_app_command_names()
    missing = registered - _HELP_CATEGORY.keys()
    assert not missing, (
        "The following slash commands are not listed in _HELP_CATEGORY "
        "(claude_discord/cogs/claude_chat.py):\n"
        + "\n".join(f"  /{name}" for name in sorted(missing))
        + "\n\nAdd each name to _HELP_CATEGORY with the appropriate section "
        '(e.g. "📌 Session") or None to hide it from /help.'
    )


def test_no_stale_entries() -> None:
    """_HELP_CATEGORY must not contain names that have no matching command.

    Prevents the dict accumulating ghost entries after a command is renamed
    or removed.
    """
    from claude_discord.cogs.claude_chat import _HELP_CATEGORY

    registered = _collect_app_command_names()
    stale = _HELP_CATEGORY.keys() - registered
    assert not stale, (
        "_HELP_CATEGORY contains command names with no matching @app_commands.command:\n"
        + "\n".join(f"  /{name}" for name in sorted(stale))
        + "\n\nRemove the stale entries from _HELP_CATEGORY "
        "(claude_discord/cogs/claude_chat.py)."
    )


def test_help_itself_is_excluded() -> None:
    """The 'help' command must be excluded from the embed (value = None).

    /help should not list itself — that would be circular and confusing.
    """
    from claude_discord.cogs.claude_chat import _HELP_CATEGORY

    assert _HELP_CATEGORY.get("help") is None, (
        "The 'help' command must have value=None in _HELP_CATEGORY so it is "
        "excluded from the /help embed."
    )


def test_section_order_matches_known_sections() -> None:
    """Every non-None value in _HELP_CATEGORY must appear in _HELP_SECTION_ORDER.

    This prevents commands from silently disappearing because their section
    name has a typo.
    """
    from claude_discord.cogs.claude_chat import _HELP_CATEGORY, _HELP_SECTION_ORDER

    known_sections = set(_HELP_SECTION_ORDER)
    bad = {
        name: section
        for name, section in _HELP_CATEGORY.items()
        if section is not None and section not in known_sections
    }
    assert not bad, (
        "The following _HELP_CATEGORY entries reference an unknown section "
        "(not in _HELP_SECTION_ORDER):\n"
        + "\n".join(f"  /{name!r}: {section!r}" for name, section in sorted(bad.items()))
        + f"\n\nKnown sections: {sorted(known_sections)}"
    )
