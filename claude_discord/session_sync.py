"""CLI session scanner for syncing Claude Code sessions with Discord.

Scans the Claude Code session storage directory (~/.claude/projects/)
to discover sessions that were started from the CLI and could be
synced as Discord threads.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# UUID pattern for session JSONL files
_SESSION_FILE_PATTERN = re.compile(r"^[a-f0-9\-]{36}\.jsonl$")

# Max summary length
_MAX_SUMMARY_LEN = 100


@dataclass(frozen=True)
class CliSession:
    """A session discovered from Claude Code CLI storage."""

    session_id: str
    working_dir: str | None
    summary: str | None
    timestamp: str | None


def scan_cli_sessions(base_path: str) -> list[CliSession]:
    """Scan a Claude Code projects directory for sessions.

    Args:
        base_path: Path to scan. Can be a project directory (containing .jsonl
                   files directly) or the parent ~/.claude/projects/ directory
                   (containing project subdirectories).

    Returns:
        List of CliSession objects discovered, sorted by timestamp descending.
    """
    base = Path(base_path)
    if not base.is_dir():
        return []

    sessions: list[CliSession] = []

    # Collect all .jsonl files — either directly in base_path or in subdirectories
    jsonl_files = list(base.glob("*.jsonl")) + list(base.glob("*/*.jsonl"))

    for jsonl_path in jsonl_files:
        if not _SESSION_FILE_PATTERN.match(jsonl_path.name):
            continue
        session = _parse_session_file(jsonl_path)
        if session:
            sessions.append(session)

    # Sort by timestamp descending (most recent first)
    sessions.sort(key=lambda s: s.timestamp or "", reverse=True)
    return sessions


def _parse_session_file(path: Path) -> CliSession | None:
    """Parse a single session JSONL file to extract metadata.

    Reads lines until the first real user message (non-meta, non-XML-prefixed)
    is found, then uses it as the session summary.
    """
    session_id = path.stem
    working_dir: str | None = None
    summary: str | None = None
    timestamp: str | None = None

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if data.get("type") != "user":
                    continue

                # Capture timestamp from any user message
                if not timestamp and data.get("timestamp"):
                    timestamp = data["timestamp"]

                # Skip meta messages
                if data.get("isMeta"):
                    continue

                content = data.get("message", {}).get("content", "")

                # Skip XML-prefixed content (internal commands)
                if content.startswith("<"):
                    continue

                # Found the first real user message
                working_dir = data.get("cwd")
                summary = content[:_MAX_SUMMARY_LEN]
                if not timestamp:
                    timestamp = data.get("timestamp")
                break

    except OSError:
        logger.debug("Failed to read session file: %s", path, exc_info=True)
        return None

    if not summary:
        return None

    return CliSession(
        session_id=session_id,
        working_dir=working_dir,
        summary=summary,
        timestamp=timestamp,
    )
