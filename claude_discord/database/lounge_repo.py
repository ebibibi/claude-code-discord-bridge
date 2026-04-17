"""AI Lounge message repository.

This module re-exports the lounge repository from claude_code_core.
Backward-compatible: all existing imports from this path continue to work.
"""

from __future__ import annotations

# Re-export everything from core (including private helpers used by tests)
from claude_code_core.lounge_repo import (
    _MAX_STORED_MESSAGES,
    LoungeMessage,
    LoungeRepository,
)

__all__ = [
    "LoungeMessage",
    "LoungeRepository",
    "_MAX_STORED_MESSAGES",
]
