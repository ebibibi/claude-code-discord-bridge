"""Parser for Claude Code CLI stream-json output.

This module re-exports the parser from claude_code_core.
Backward-compatible: all existing imports from this path continue to work.
"""

from __future__ import annotations

# Re-export everything from core (including private helpers used by tests)
from claude_code_core.parser import (
    _parse_ask_questions,
    _parse_todo_items,
    parse_line,
)

__all__ = ["parse_line", "_parse_ask_questions", "_parse_todo_items"]
