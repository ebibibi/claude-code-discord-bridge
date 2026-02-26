"""File attachment sender for session-complete events.

Collects files written/edited during a Claude session and sends them as
Discord attachments when the session completes successfully.

Configuration (environment variables):
    CCDB_ATTACH_WRITTEN_FILES: Set to "false", "0", or "no" to disable.
        Defaults to enabled.
    CCDB_ATTACH_MAX_BYTES: Per-file size limit in bytes.
        Defaults to 524288 (512 KB).

Discord limits: 10 files per message, 8 MB per file (non-boosted server).
Files exceeding the configured size limit or detected as binary are skipped.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
from pathlib import Path

import discord

logger = logging.getLogger(__name__)

# Default per-file size limit — generous for source code, avoids accidental
# large binary uploads.
_DEFAULT_MAX_FILE_BYTES = 512 * 1024  # 512 KB

# Discord API hard limit: 10 files per message.
_MAX_FILES_PER_MESSAGE = 10


def _is_enabled() -> bool:
    """Return False when CCDB_ATTACH_WRITTEN_FILES is set to a falsy value."""
    return os.environ.get("CCDB_ATTACH_WRITTEN_FILES", "true").lower() not in (
        "false",
        "0",
        "no",
    )


def _max_file_bytes() -> int:
    """Return the per-file size limit from env, falling back to the default."""
    raw = os.environ.get("CCDB_ATTACH_MAX_BYTES", "")
    if raw:
        with contextlib.suppress(ValueError):
            return int(raw)
    return _DEFAULT_MAX_FILE_BYTES


def _is_binary(data: bytes) -> bool:
    """Heuristic: treat a file as binary if it contains a null byte in the
    first 8 KB.  Null bytes never appear in valid UTF-8 source files.
    """
    return b"\x00" in data[:8192]


def _relative_path(file_path: str, working_dir: str | None) -> str:
    """Return a display name for the file.

    Prefers a path relative to *working_dir* so the user sees ``src/foo.py``
    rather than the full absolute path.  Falls back to the bare filename when
    the file lives outside *working_dir* or no *working_dir* is given.
    """
    if working_dir:
        with contextlib.suppress(ValueError):
            return str(Path(file_path).relative_to(working_dir))
    return Path(file_path).name


def collect_discord_files(
    file_paths: list[str],
    working_dir: str | None,
    max_bytes: int | None = None,
) -> list[discord.File]:
    """Read qualifying files from disk and return ``discord.File`` objects.

    Each file is read into an in-memory ``BytesIO`` buffer so that callers
    can safely delete the source file (e.g. worktree cleanup) after this
    function returns without invalidating the attachment.

    Skips files that:
    * Do not exist on disk
    * Exceed *max_bytes* (default: 512 KB)
    * Appear to be binary (contain a null byte in the first 8 KB)

    Args:
        file_paths: Absolute or working-dir-relative paths to attach.
        working_dir: Base directory used to compute relative display names.
        max_bytes: Per-file size limit.  ``None`` reads from env / default.

    Returns:
        List of ``discord.File`` objects, ready to pass to ``thread.send()``.
    """
    limit = max_bytes if max_bytes is not None else _max_file_bytes()
    result: list[discord.File] = []

    for path_str in file_paths:
        path = Path(path_str)

        if not path.exists() or not path.is_file():
            logger.debug("Skipping missing or non-file path: %s", path)
            continue

        try:
            size = path.stat().st_size
        except OSError:
            logger.debug("Cannot stat file, skipping: %s", path)
            continue

        if size > limit:
            logger.info(
                "Skipping file exceeding size limit (%d > %d bytes): %s",
                size,
                limit,
                path,
            )
            continue

        try:
            data = path.read_bytes()
        except OSError:
            logger.debug("Cannot read file, skipping: %s", path, exc_info=True)
            continue

        if _is_binary(data):
            logger.debug("Skipping binary file: %s", path)
            continue

        display_name = _relative_path(path_str, working_dir)
        result.append(discord.File(io.BytesIO(data), filename=display_name))

    return result


async def send_written_files(
    thread: discord.Thread,
    file_paths: list[str],
    working_dir: str | None,
) -> None:
    """Send files created during a Claude session as Discord attachments.

    Called from ``EventProcessor._on_complete()`` after a successful session.
    Sends in batches of up to 10 (Discord API limit).  Any Discord error is
    suppressed so that a network hiccup never kills the session-complete flow.

    Does nothing when:
    * ``CCDB_ATTACH_WRITTEN_FILES`` is falsy
    * *file_paths* is empty
    * All files fail qualification (binary / missing / oversized)

    Args:
        thread: Discord thread to post attachments to.
        file_paths: Paths of files written/edited during the session.
        working_dir: Runner working directory for relative display names.
    """
    if not _is_enabled() or not file_paths:
        return

    files = collect_discord_files(file_paths, working_dir)
    if not files:
        return

    for i in range(0, len(files), _MAX_FILES_PER_MESSAGE):
        batch = files[i : i + _MAX_FILES_PER_MESSAGE]
        with contextlib.suppress(Exception):
            await thread.send(
                content="-# 📎 Files written this session" if i == 0 else None,
                files=batch,
            )
