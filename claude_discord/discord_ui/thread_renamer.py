"""Thread title auto-renamer — uses `claude -p` to generate a concise title.

After a new thread is created from a user's first message, this module runs
a lightweight one-shot call to generate a descriptive, short thread title.

The result is applied by renaming the Discord thread via thread.edit(name=...).
Falls back silently (no rename) on any error or timeout.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
Generate a short, descriptive title (max 80 characters) for a chat thread.
The title should clearly summarize the user's request or topic.
Reply with ONLY the title — no quotes, no punctuation at the end, no explanation.

[USER MESSAGE]
{text}
"""

_TIMEOUT_SECONDS = 30
_MAX_TITLE_LENGTH = 90  # Discord thread name limit is 100; leave a small margin

# Environment variables that tie a Claude process to a specific Discord session.
# Removing them prevents SessionStart hooks from treating this utility call
# as a user-facing Discord conversation (which would create spurious threads
# or post messages to the wrong channel).
_DISCORD_SESSION_ENV_KEYS: frozenset[str] = frozenset(
    {
        "DISCORD_THREAD_ID",
        "CCDB_API_URL",
        "CCDB_API_SECRET",
    }
)


def _clean_env() -> dict[str, str]:
    """Return os.environ without Discord session variables."""
    return {k: v for k, v in os.environ.items() if k not in _DISCORD_SESSION_ENV_KEYS}


async def suggest_title(
    user_message: str,
    claude_command: str = "claude",
) -> str | None:
    """Call `claude -p` and return a short thread title.

    Returns None on empty input, timeout, or any error, so the caller can
    keep the original thread name without any visible failure.
    Prompt is passed as a direct argument to the binary (no shell, no injection risk).
    The subprocess runs without Discord session env vars so that SessionStart
    hooks do not treat this utility call as a Discord conversation.
    """
    if not user_message.strip():
        return None

    prompt = _PROMPT_TEMPLATE.format(text=user_message[:2000])

    try:
        proc = await asyncio.create_subprocess_exec(
            claude_command,
            "-p",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_clean_env(),
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning("thread title renamer timed out after %ds", _TIMEOUT_SECONDS)
            return None

        raw = stdout.decode(errors="replace").strip()
        # Strip surrounding quotes that some models add
        raw = raw.strip("\"'")
        title = raw.strip()

        if not title:
            logger.debug("thread title renamer returned empty output")
            return None

        if len(title) > _MAX_TITLE_LENGTH:
            title = title[:_MAX_TITLE_LENGTH]

        logger.debug("thread title suggestion: %r", title)
        return title

    except Exception:
        logger.warning("thread title renamer failed", exc_info=True)
        return None
