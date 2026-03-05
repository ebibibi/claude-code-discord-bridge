"""Thread inbox classifier — uses `claude -p` to determine if a session is done.

After a Claude Code session ends, this module runs a lightweight one-shot
classification call to determine whether the thread requires user action.

Classification result:
  waiting   — Claude clearly expects a reply (question, request for confirmation, etc.)
  done      — Claude considers the task complete; no reply needed
  ambiguous — Cannot be determined from the message alone

When the result is 'done', the thread is NOT added to the inbox.
When 'waiting' or 'ambiguous', it is persisted so the dashboard can surface it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

logger = logging.getLogger(__name__)

ClassifyResult = Literal["waiting", "done", "ambiguous"]

_PROMPT_TEMPLATE = """\
Below is the last message sent by an AI assistant.
After sending this message, does the AI expect a reply from the user?

[MESSAGE]
{text}

Reply with exactly one word — no other text:
- waiting  : user reply, confirmation, or action is required
- done     : the task is complete and no reply is needed
- ambiguous: cannot be determined from the message alone
"""

_VALID = frozenset({"waiting", "done", "ambiguous"})
_TIMEOUT_SECONDS = 30

# Environment variables that tie a Claude process to a specific Discord session.
# Removing them prevents SessionStart hooks from treating this utility call
# as a user-facing Discord conversation.
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


async def classify(
    last_text: str,
    claude_command: str = "claude",
) -> ClassifyResult:
    """Call `claude -p` and parse waiting/done/ambiguous.

    Falls back to 'waiting' on any error so threads are never silently lost.
    Prompt is passed as a direct argument to the binary (no shell, no injection risk).
    The subprocess runs without Discord session env vars so that SessionStart
    hooks do not treat this utility call as a Discord conversation.
    """
    if not last_text.strip():
        return "ambiguous"

    prompt = _PROMPT_TEMPLATE.format(text=last_text[:2000])

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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning("inbox classifier timed out after %ds", _TIMEOUT_SECONDS)
            return "waiting"

        raw = stdout.decode(errors="replace").strip().lower()
        # Accept the first word in case the model adds punctuation or whitespace
        word = raw.split()[0] if raw.split() else ""
        if word in _VALID:
            result: ClassifyResult = word  # type: ignore[assignment]
            logger.debug("inbox classify result=%s raw=%r", result, raw)
            return result

        logger.debug("inbox classify unexpected output=%r, defaulting to ambiguous", raw)
        return "ambiguous"

    except Exception:
        logger.warning("inbox classify failed, defaulting to waiting", exc_info=True)
        return "waiting"
