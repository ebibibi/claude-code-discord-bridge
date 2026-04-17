"""JSONL session rewind utilities.

This module re-exports the rewind utilities from claude_code_core.
Backward-compatible: all existing imports from this path continue to work.
"""

from __future__ import annotations

# Re-export everything from core (including private helpers used by tests)
from claude_code_core.rewind import (
    TurnEntry,
    _cwd_to_project_dir,
    _extract_text,
    find_session_jsonl,
    parse_user_turns,
    truncate_jsonl_at_line,
)

__all__ = [
    "TurnEntry",
    "_cwd_to_project_dir",
    "_extract_text",
    "find_session_jsonl",
    "parse_user_turns",
    "truncate_jsonl_at_line",
]
