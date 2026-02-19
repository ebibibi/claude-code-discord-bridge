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


def scan_cli_sessions(
    base_path: str,
    *,
    limit: int = 50,
    max_lines_per_file: int = 20,
) -> list[CliSession]:
    """Scan a Claude Code projects directory for sessions.

    Args:
        base_path: Path to scan. Can be a project directory (containing .jsonl
                   files directly) or the parent ~/.claude/projects/ directory
                   (containing project subdirectories).
        limit: Maximum number of sessions to return. Files are sorted by
               modification time (newest first) and only the newest ``limit``
               files are parsed. Set to 0 for no limit.
        max_lines_per_file: Maximum lines to read per file when searching for
                            the first user message. Prevents reading entire
                            multi-MB session files.

    Returns:
        List of CliSession objects discovered, sorted by timestamp descending.
    """
    base = Path(base_path)
    if not base.is_dir():
        return []

    # Collect all .jsonl files — either directly in base_path or in subdirectories
    jsonl_files = list(base.glob("*.jsonl")) + list(base.glob("*/*.jsonl"))

    # Filter to session files only
    jsonl_files = [p for p in jsonl_files if _SESSION_FILE_PATTERN.match(p.name)]

    # Sort by modification time (newest first) and apply limit
    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit > 0:
        jsonl_files = jsonl_files[:limit]

    sessions: list[CliSession] = []
    for jsonl_path in jsonl_files:
        session = _parse_session_file(jsonl_path, max_lines=max_lines_per_file)
        if session:
            sessions.append(session)

    # Sort by timestamp descending (most recent first)
    sessions.sort(key=lambda s: s.timestamp or "", reverse=True)
    return sessions


def _parse_session_file(path: Path, *, max_lines: int = 20) -> CliSession | None:
    """Parse a single session JSONL file to extract metadata.

    Reads up to ``max_lines`` lines searching for the first real user message
    (non-meta, non-XML-prefixed) to use as the session summary.
    """
    session_id = path.stem
    working_dir: str | None = None
    summary: str | None = None
    timestamp: str | None = None

    try:
        with open(path) as f:
            lines_read = 0
            for line in f:
                lines_read += 1
                if lines_read > max_lines:
                    break
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
