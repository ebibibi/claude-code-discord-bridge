"""Auto-load memory files for cross-session context.

Reads MEMORY.md to find files marked with ★★★ (auto-load section),
then reads their content to inject into the AI agent's system prompt.

This ensures every new session starts with critical context (company charter,
behavior rules, active handoffs) without relying on the AI to manually
read the right files.

Memory resolution order (first match wins):
  1. <working_dir>/memory/           — git-based memory (harness-independent)
  2. ~/.claude/projects/<slug>/memory/ — Claude Code legacy path
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Claude Code legacy path (fallback only).
_CLAUDE_DIR = Path.home() / ".claude" / "projects"

# Maximum total characters to inject (prevent prompt overflow).
_MAX_TOTAL_CHARS = 12_000


def _working_dir_to_project_slug(working_dir: str) -> str:
    """Convert a working directory to Claude Code's project slug.

    /home/ubuntu/ec-automation-system → -home-ubuntu-ec-automation-system
    """
    return working_dir.replace("/", "-")


def _find_auto_load_files(memory_md: str) -> list[str]:
    """Parse MEMORY.md and extract filenames from the auto-load section.

    Looks for the section containing '★★★' and 'auto-load', then extracts
    all markdown link targets like [label](filename.md).
    """
    lines = memory_md.split("\n")
    in_auto_load = False
    filenames: list[str] = []

    for line in lines:
        # Detect start of auto-load section
        if "★★★" in line and "auto-load" in line.lower():
            in_auto_load = True
            continue

        # Stop at next section header
        if in_auto_load and line.startswith("## "):
            break

        if in_auto_load:
            # Extract (filename.md) from markdown links
            for match in re.finditer(r"\[.*?\]\(([^)]+\.md)\)", line):
                filenames.append(match.group(1))

    return filenames


def _resolve_memory_dir(working_dir: str) -> Path | None:
    """Resolve memory directory, preferring git-based over Claude Code legacy.

    Resolution order:
      1. MEMORY_DIR env var (explicit override)
      2. <working_dir>/memory/ (git-based, harness-independent)
      3. ~/.claude/projects/<slug>/memory/ (Claude Code legacy)
    """
    # 1. Explicit override via env var
    env_override = os.environ.get("MEMORY_DIR")
    if env_override:
        p = Path(env_override)
        if (p / "MEMORY.md").exists():
            logger.info("Using MEMORY_DIR override: %s", p)
            return p

    # 2. Git-based memory (harness-independent)
    git_memory = Path(working_dir) / "memory"
    if (git_memory / "MEMORY.md").exists():
        logger.info("Using git-based memory: %s", git_memory)
        return git_memory

    # 3. Claude Code legacy path (fallback)
    slug = _working_dir_to_project_slug(working_dir)
    legacy = _CLAUDE_DIR / slug / "memory"
    if (legacy / "MEMORY.md").exists():
        logger.info("Using Claude Code legacy memory: %s", legacy)
        return legacy

    return None


def load_auto_memory(working_dir: str | None) -> str | None:
    """Load auto-load memory files and return formatted context string.

    Returns None if no memory is found or working_dir is not set.
    """
    if not working_dir:
        return None

    memory_dir = _resolve_memory_dir(working_dir)
    if memory_dir is None:
        logger.debug("No memory directory found for %s", working_dir)
        return None

    memory_md_path = memory_dir / "MEMORY.md"

    try:
        memory_md = memory_md_path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Failed to read MEMORY.md", exc_info=True)
        return None

    filenames = _find_auto_load_files(memory_md)
    if not filenames:
        logger.debug("No auto-load files found in MEMORY.md")
        return None

    parts: list[str] = []
    total_chars = 0

    for filename in filenames:
        filepath = memory_dir / filename
        if not filepath.exists():
            logger.debug("Auto-load file missing: %s", filepath)
            continue

        try:
            content = filepath.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Failed to read auto-load file %s", filename, exc_info=True)
            continue

        # Strip frontmatter (--- ... ---) for cleaner injection
        stripped = _strip_frontmatter(content)

        if total_chars + len(stripped) > _MAX_TOTAL_CHARS:
            logger.info(
                "Auto-load size limit reached (%d chars), skipping %s",
                total_chars,
                filename,
            )
            break

        parts.append(f"### {filename}\n{stripped}")
        total_chars += len(stripped)

    if not parts:
        return None

    header = (
        "[AUTO-LOADED MEMORY — 以下はMEMORY.mdの★★★セクションから自動読み込みされた重要メモリ。"
        "毎セッション必読の情報。]\n"
    )
    return header + "\n---\n".join(parts)


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from markdown content."""
    if not content.startswith("---"):
        return content
    # Find the closing ---
    end = content.find("---", 3)
    if end == -1:
        return content
    return content[end + 3:].lstrip("\n")
