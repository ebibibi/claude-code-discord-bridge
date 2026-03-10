"""Statusline runner for Discord.

Reads the ``statusLine.command`` from ``~/.claude/settings.json``, executes it
with a JSON payload describing the current session state, and returns a
Discord-ready plain-text string.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_STATUSLINE_TIMEOUT = 10.0

# Matches the bar pattern emitted by render_bar() in statusline scripts:
#   ESC[48;2;R;G;Bm  <filled spaces>  ESC[0m
#   ESC[48;2;60;60;60m  <empty spaces>  ESC[0m
_BAR_RE = re.compile(
    r"\x1b\[48;2;\d+;\d+;\d+m( *)\x1b\[0m"
    r"\x1b\[48;2;60;60;60m( *)\x1b\[0m"
)

# Matches any remaining ANSI escape sequences.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")


def read_statusline_command(settings_path: str | None = None) -> str | None:
    """Return the ``statusLine.command`` string from ``~/.claude/settings.json``.

    Returns ``None`` if the file does not exist, cannot be parsed, or does not
    contain a ``statusLine`` entry of type ``"command"``.
    """
    if settings_path is None:
        settings_path = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(settings_path, encoding="utf-8") as fh:
            data = json.load(fh)
        entry = data.get("statusLine") or data.get("statusline")
        if isinstance(entry, dict) and entry.get("type") == "command":
            return entry.get("command") or None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def build_statusline_json(
    cwd: str,
    model_id: str,
    model_display_name: str,
    context_size: int,
    input_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
) -> str:
    """Build the JSON string expected by statusline commands."""
    return json.dumps(
        {
            "workspace": {"current_dir": cwd},
            "model": {
                "id": model_id,
                "display_name": model_display_name,
            },
            "context_window": {
                "context_window_size": context_size,
                "current_usage": {
                    "input_tokens": input_tokens,
                    "cache_creation_input_tokens": cache_creation_tokens,
                    "cache_read_input_tokens": cache_read_tokens,
                },
            },
        }
    )


def _bars_to_unicode(text: str) -> str:
    """Replace ANSI space-based bars with Unicode block characters.

    ``render_bar()`` in statusline scripts outputs filled/empty sections as
    space characters with coloured ANSI backgrounds.  Stripping ANSI directly
    would leave invisible blank spans.  This converts each bar span to
    ``█`` (filled) and ``░`` (empty) before ANSI removal.
    """

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        filled = len(m.group(1))
        empty = len(m.group(2))
        return "█" * filled + "░" * empty

    return _BAR_RE.sub(_replace, text)


def strip_ansi(text: str) -> str:
    """Remove all remaining ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)


def convert_for_discord(raw: str) -> str:
    """Convert raw statusline output (ANSI) to Discord-ready plain text."""
    return strip_ansi(_bars_to_unicode(raw))


async def render_statusline(
    command: str,
    json_input: str,
    timeout: float = _STATUSLINE_TIMEOUT,
) -> str | None:
    """Execute *command* with *json_input* on stdin and return Discord-ready text.

    Returns ``None`` if the command fails, times out, or produces empty output.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(json_input.encode()),
            timeout=timeout,
        )
        raw = stdout.decode(errors="replace")
        return convert_for_discord(raw).strip() or None
    except (TimeoutError, OSError, Exception):
        logger.debug("Statusline command failed or timed out", exc_info=True)
        return None
