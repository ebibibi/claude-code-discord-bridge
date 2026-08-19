"""CI guard: _HELP_CATEGORY must stay in sync with top-level slash commands."""

from __future__ import annotations

import ast
import pathlib

_COGS_DIR = pathlib.Path(__file__).parent.parent / "claude_discord" / "cogs"


def _keyword_name(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def _is_app_commands_call(call: ast.Call, attribute: str) -> bool:
    function = call.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == attribute
        and isinstance(function.value, ast.Name)
        and function.value.id == "app_commands"
    )


def _collect_app_command_names() -> set[str]:
    """Return every top-level application command and command-group name."""
    names: set[str] = set()
    for path in sorted(_COGS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not _is_app_commands_call(decorator, "command"):
                    continue
                name = _keyword_name(decorator)
                if name is not None:
                    names.add(name)

        # A slash-command group is registered as one top-level command. Only
        # inspect direct class assignments so nested child groups are not added
        # separately to the /help category map.
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for statement in class_node.body:
                value: ast.expr | None = None
                if isinstance(statement, ast.Assign):
                    value = statement.value
                elif isinstance(statement, ast.AnnAssign):
                    value = statement.value
                if not isinstance(value, ast.Call):
                    continue
                if not _is_app_commands_call(value, "Group"):
                    continue
                name = _keyword_name(value)
                if name is not None:
                    names.add(name)

    return names


def test_all_commands_covered() -> None:
    """Every top-level slash command must have a help category."""
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
    """_HELP_CATEGORY must not contain unregistered top-level commands."""
    from claude_discord.cogs.claude_chat import _HELP_CATEGORY

    registered = _collect_app_command_names()
    stale = _HELP_CATEGORY.keys() - registered
    assert not stale, (
        "_HELP_CATEGORY contains command names with no matching application command:\n"
        + "\n".join(f"  /{name!r}" for name in sorted(stale))
        + "\n\nRemove the stale entries from _HELP_CATEGORY "
        "(claude_discord/cogs/claude_chat.py)."
    )


def test_help_itself_is_excluded() -> None:
    """The help command must be excluded from its own embed."""
    from claude_discord.cogs.claude_chat import _HELP_CATEGORY

    assert _HELP_CATEGORY.get("help") is None, (
        "The 'help' command must have value=None in _HELP_CATEGORY so it is "
        "excluded from the /help embed."
    )


def test_section_order_matches_known_sections() -> None:
    """Every non-None category must appear in _HELP_SECTION_ORDER."""
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
