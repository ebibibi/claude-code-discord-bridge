"""Session repository for thread-to-session mapping.

This module re-exports the session repository from claude_code_core.
Backward-compatible: all existing imports from this path continue to work.
"""

from __future__ import annotations

# Re-export everything from core
from claude_code_core.session_repo import (
    SessionRecord,
    SessionRepository,
    UsageStatsRepository,
)

__all__ = [
    "SessionRecord",
    "SessionRepository",
    "UsageStatsRepository",
]
